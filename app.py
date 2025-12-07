import streamlit as st
import pandas as pd
import io
import os

# --- CONFIGURAZIONE ---
st.set_page_config(page_title="Mappatura Bilancio PRO", layout="wide")
DEFAULT_SCHEMA_FILENAME = "schema_ftc.xlsx"

def load_schema_logic():
    """Gestisce il caricamento dello schema FTC (Automatico o Manuale)"""
    schema_df = None
    
    # 1. Cerca il file nella cartella locale
    if os.path.exists(DEFAULT_SCHEMA_FILENAME):
        try:
            schema_df = pd.read_excel(DEFAULT_SCHEMA_FILENAME)
            st.success(f"✅ Schema FTC caricato automaticamente da '{DEFAULT_SCHEMA_FILENAME}'")
        except Exception as e:
            st.error(f"Errore lettura file default: {e}")

    # 2. Se non c'è il file locale, mostra l'uploader
    if schema_df is None:
        st.warning(f"File '{DEFAULT_SCHEMA_FILENAME}' non trovato nella cartella. Caricalo manualmente qui sotto.")
        uploaded_schema = st.file_uploader("Carica Piano Conti FTC (Excel)", type=['xlsx'])
        if uploaded_schema:
            schema_df = pd.read_excel(uploaded_schema)
            
    return schema_df

def main():
    st.title("📊 Mappatura Bilancio Avanzata")
    
    # --- FASE 1: CARICAMENTO SCHEMA FTC (Default o Manuale) ---
    st.sidebar.header("1. Configurazione")
    df_schema = load_schema_logic()
    
    if df_schema is None:
        st.stop() # Ferma tutto se non c'è lo schema

    # Preparazione Opzioni Schema (preservando ordine)
    schema_opts = []
    sort_order_map = {} 
    counter = 0
    for index, row in df_schema.iterrows():
        if pd.isna(row.iloc[0]) and pd.isna(row.iloc[1]): continue
        code = str(row.iloc[0]).strip()
        desc = str(row.iloc[1]).strip() if not pd.isna(row.iloc[1]) else ""
        full_label = f"{code} - {desc}"
        schema_opts.append(full_label)
        sort_order_map[full_label] = counter
        counter += 1

    # --- FASE 2: INPUT DATI ---
    st.header("Caricamento Dati")
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("A. Nuova Situazione Contabile")
        source_file = st.file_uploader("Carica Bilancio Verifica (Excel)", type=['xlsx'], key="src")
        
    with col2:
        st.subheader("B. Mappatura Salvata (Opzionale)")
        mapping_file = st.file_uploader("Carica un lavoro precedente (Excel)", type=['xlsx'], key="map")
        st.caption("Se carichi questo file, il programma applicherà automaticamente gli abbinamenti ai conti che riconosce.")

    if source_file:
        try:
            # --- LETTURA SOURCE ---
            df_source = pd.read_excel(source_file)
            df_source.columns = df_source.columns.str.strip()
            
            # Identificazione colonne
            cols = df_source.columns
            c_conto = next((c for c in cols if 'conto' in c.lower() and 'des' not in c.lower()), df_source.columns[0])
            c_desc = next((c for c in cols if 'desc' in c.lower()), df_source.columns[1])
            c_saldo = next((c for c in cols if 'saldo' in c.lower() or 'imp' in c.lower()), df_source.columns[-1])
            
            # Inizializza colonna destinazione
            if 'Destinazione_FTC' not in df_source.columns:
                df_source['Destinazione_FTC'] = "DA ABBINARE"

            # --- LOGICA DI RECUPERO MAPPATURA ---
            msg_recupero = ""
            if mapping_file:
                try:
                    df_old = pd.read_excel(mapping_file)
                    # Cerchiamo le colonne nel file vecchio
                    old_cols = df_old.columns
                    c_conto_old = next((c for c in old_cols if 'conto' in c.lower() and 'des' not in c.lower()), None)
                    
                    # Cerchiamo la colonna che contiene la mappatura (Destinazione_FTC o combinazione Codice/Desc)
                    if 'Destinazione_FTC' in old_cols:
                        # Creiamo un dizionario { Conto: Mappatura }
                        mappa_dict = pd.Series(df_old['Destinazione_FTC'].values, index=df_old[c_conto_old].astype(str)).to_dict()
                        
                        # Applichiamo la mappa
                        def applica_mappa(riga):
                            conto_str = str(riga[c_conto])
                            # Se il conto esiste nel vecchio file E non è vuoto, lo prendiamo
                            if conto_str in mappa_dict and pd.notna(mappa_dict[conto_str]) and mappa_dict[conto_str] != "DA ABBINARE":
                                return mappa_dict[conto_str]
                            return riga['Destinazione_FTC']

                        df_source['Destinazione_FTC'] = df_source.apply(applica_mappa, axis=1)
                        msg_recupero = "✅ Mappatura precedente applicata con successo!"
                    
                    elif 'Codice_Dest_FTC' in old_cols:
                         # Caso in cui carichiamo il file finale esportato (codice e desc separati)
                         # Ricostruiamo la stringa "CODICE - DESC"
                         df_old['Ricostruita'] = df_old['Codice_Dest_FTC'].astype(str) + " - " + df_old['Desc_Dest_FTC'].astype(str)
                         mappa_dict = pd.Series(df_old['Ricostruita'].values, index=df_old[c_conto_old].astype(str)).to_dict()
                         
                         def applica_mappa_split(riga):
                            conto_str = str(riga[c_conto])
                            val = mappa_dict.get(conto_str)
                            # Pulizia stringhe tipo "nan - nan"
                            if val and "nan - " not in val and val != "DA ABBINARE":
                                return val
                            return riga['Destinazione_FTC']
                            
                         df_source['Destinazione_FTC'] = df_source.apply(applica_mappa_split, axis=1)
                         msg_recupero = "✅ Mappatura recuperata dal file esportato!"

                except Exception as ex:
                    st.warning(f"Impossibile leggere il file di mappatura precedente: {ex}")

            st.divider()
            if msg_recupero: st.success(msg_recupero)

            # --- EDITOR E ALBERO ---
            col_map, col_tree = st.columns([1.6, 1])
            
            with col_map:
                st.subheader("Tabella di Lavoro")
                edited_df = st.data_editor(
                    df_source,
                    column_config={
                        c_conto: st.column_config.TextColumn("Conto", disabled=True),
                        c_desc: st.column_config.TextColumn("Descrizione", disabled=True),
                        c_saldo: st.column_config.NumberColumn("Saldo", format="€ %.2f", disabled=True),
                        "Destinazione_FTC": st.column_config.SelectboxColumn(
                            "Abbinamento FTC",
                            width="large",
                            options=["DA ABBINARE"] + schema_opts,
                            required=True,
                        )
                    },
                    hide_index=True,
                    use_container_width=True,
                    height=600
                )

            with col_tree:
                st.subheader("Anteprima Albero FTC")
                mapped_data = edited_df[edited_df['Destinazione_FTC'] != "DA ABBINARE"]
                
                if not mapped_data.empty:
                    groups = mapped_data.groupby('Destinazione_FTC')
                    used_keys = list(groups.groups.keys())
                    sorted_keys = sorted(used_keys, key=lambda x: sort_order_map.get(x, 999999))
                    
                    tot_gen = 0
                    for dest in sorted_keys:
                        grp = groups.get_group(dest)
                        sub = grp[c_saldo].sum()
                        tot_gen += sub
                        with st.expander(f"{dest} ➡️ € {sub:,.2f}"):
                            st.dataframe(grp[[c_conto, c_desc, c_saldo]], hide_index=True)
                    
                    st.metric("Totale", f"€ {tot_gen:,.2f}")
                else:
                    st.info("Nessun conto abbinato.")

            # --- EXPORT ---
            # Logica per separare Codice e Descrizione per l'export
            def split_mapping(val):
                if val == "DA ABBINARE" or pd.isna(val): return "", ""
                parts = str(val).split(' - ', 1)
                return (parts[0], parts[1]) if len(parts) == 2 else (val, "")

            export_df = edited_df.copy()
            export_df[['Codice_Dest_FTC', 'Desc_Dest_FTC']] = export_df['Destinazione_FTC'].apply(
                lambda x: pd.Series(split_mapping(x))
            )
            
            # Riordino colonne per pulizia
            final_cols = [c_conto, c_desc, c_saldo, 'Destinazione_FTC', 'Codice_Dest_FTC', 'Desc_Dest_FTC']
            remaining = [c for c in export_df.columns if c not in final_cols]
            export_df = export_df[final_cols + remaining]

            st.divider()
            st.subheader("Salvataggio")
            st.caption("Scarica questo file. Potrai ricaricarlo come 'Mappatura Salvata' la prossima volta per riprendere il lavoro.")
            
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                export_df.to_excel(writer, index=False, sheet_name='Lavoro_Completo')
                # Aggiungiamo il sintetico per comodità
                if not mapped_data.empty:
                    summary = mapped_data.groupby('Destinazione_FTC')[c_saldo].sum().reset_index()
                    summary.to_excel(writer, index=False, sheet_name='Sintetico')

            st.download_button(
                "💾 Salva File di Lavoro (Excel)",
                data=output.getvalue(),
                file_name="Mappatura_FTC_Salvata.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

        except Exception as e:
            st.error(f"Errore critico: {e}")

if __name__ == "__main__":
    main()
