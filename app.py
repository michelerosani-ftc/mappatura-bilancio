import streamlit as st
import pandas as pd
import io
import os

# --- CONFIGURAZIONE ---
st.set_page_config(page_title="Mappatura Bilancio PRO", layout="wide")
DEFAULT_SCHEMA_FILENAME = "schema_ftc.xlsx"

# CSS PERSONALIZZATO PER RIDURRE IL FONT NELL'ALBERO
st.markdown("""
<style>
    /* Riduce la dimensione del font nell'expander (i titoli dell'albero) */
    .streamlit-expanderHeader {
        font-size: 14px !important;
        padding-top: 5px !important;
        padding-bottom: 5px !important;
    }
    /* Riduce un po' il font delle tabelle per compattare */
    div[data-testid="stDataFrame"] {
        font-size: 13px !important;
    }
</style>
""", unsafe_allow_html=True)

def load_schema_logic():
    """Gestisce il caricamento dello schema FTC"""
    schema_df = None
    if os.path.exists(DEFAULT_SCHEMA_FILENAME):
        try:
            schema_df = pd.read_excel(DEFAULT_SCHEMA_FILENAME)
            st.success(f"✅ Schema FTC caricato automaticamente")
        except Exception as e:
            st.error(f"Errore lettura file default: {e}")

    if schema_df is None:
        st.warning(f"File '{DEFAULT_SCHEMA_FILENAME}' non trovato. Caricalo manualmente.")
        uploaded_schema = st.file_uploader("Carica Piano Conti FTC (Excel)", type=['xlsx'])
        if uploaded_schema:
            schema_df = pd.read_excel(uploaded_schema)
            
    return schema_df

def main():
    st.title("📊 Mappatura Bilancio Avanzata")
    
    # --- 1. CONFIGURAZIONE ---
    st.sidebar.header("1. Configurazione")
    df_schema = load_schema_logic()
    
    if df_schema is None:
        st.stop() 

    # Preparazione Opzioni Schema
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

    # --- 2. INPUT DATI ---
    st.header("Caricamento Dati")
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("A. Situazione Contabile")
        source_file = st.file_uploader("Carica Excel", type=['xlsx'], key="src")
        
    with col2:
        st.subheader("B. Recupera Lavoro (Opzionale)")
        mapping_file = st.file_uploader("Carica file precedente", type=['xlsx'], key="map")

    if source_file:
        try:
            # --- LETTURA SOURCE ---
            df_source = pd.read_excel(source_file)
            df_source.columns = df_source.columns.str.strip()
            
            # --- RICONOSCIMENTO COLONNE ---
            cols = df_source.columns
            c_conto = next((c for c in cols if 'conto' in c.lower() and 'des' not in c.lower()), cols[0])
            c_desc = next((c for c in cols if 'desc' in c.lower()), cols[1])
            
            # Cerca il Saldo Finale
            saldo_candidates = [c for c in cols if 'saldo' in c.lower() or 'imp' in c.lower()]
            c_saldo = None
            for cand in saldo_candidates:
                if 'fin' in cand.lower() or 'chiu' in cand.lower():
                    c_saldo = cand
                    break
            if c_saldo is None and saldo_candidates: c_saldo = saldo_candidates[-1]
            if c_saldo is None: c_saldo = cols[-1]

            # --- PULIZIA DATI ---
            rows_before = len(df_source)
            df_source[c_conto] = df_source[c_conto].astype(str).str.strip()
            
            # 1. Gestione Eccezioni (14 e 40)
            target_14 = ['14/0000/0000', '14/00000000', '1400000000']
            target_40 = ['40/0000/0000', '40/00000000', '4000000000']
            df_source.loc[df_source[c_conto].isin(target_14), c_conto] = '14/0000/0001'
            df_source.loc[df_source[c_conto].isin(target_40), c_conto] = '40/0000/0001'
            
            # 2. Rimozione Mastri/Sottomastri (che finiscono con 0000)
            df_source = df_source[~df_source[c_conto].str.endswith('0000')]
            
            # 3. Rimozione righe vuote
            df_source = df_source[df_source[c_conto] != 'nan']
            df_source = df_source.dropna(subset=[c_saldo])
            
            # --- RIMOZIONE COLONNE INUTILI ---
            cols_to_drop = [c for c in df_source.columns if any(x in c.lower() for x in ['dare', 'avere', 'apertura'])]
            if c_saldo in cols_to_drop:
                cols_to_drop.remove(c_saldo)
            
            if cols_to_drop:
                df_source = df_source.drop(columns=cols_to_drop)
                st.caption(f"Colonne nascoste: {', '.join(cols_to_drop)}")

            st.divider()

            # --- RECUPERO MAPPATURA ---
            if 'Destinazione_FTC' not in df_source.columns:
                df_source['Destinazione_FTC'] = "DA ABBINARE"

            if mapping_file:
                try:
                    df_old = pd.read_excel(mapping_file)
                    old_cols = df_old.columns
                    k_conto = next((c for c in old_cols if 'cod' in c.lower() and 'contab' in c.lower()), None)
                    if not k_conto: k_conto = next((c for c in old_cols if 'conto' in c.lower()), None)
                    
                    mappa_dict = {}
                    if k_conto:
                        if 'Cod distinte' in old_cols and 'Descrizione distinte' in old_cols:
                             df_old['Full_Dest'] = df_old['Cod distinte'].astype(str) + " - " + df_old['Descrizione distinte'].astype(str)
                             mappa_dict = pd.Series(df_old['Full_Dest'].values, index=df_old[k_conto].astype(str)).to_dict()
                        elif 'Destinazione_FTC' in old_cols:
                             mappa_dict = pd.Series(df_old['Destinazione_FTC'].values, index=df_old[k_conto].astype(str)).to_dict()
                    
                    if mappa_dict:
                        def applica_mappa(riga):
                            c = str(riga[c_conto])
                            val = mappa_dict.get(c)
                            if val and "nan - " not in str(val) and val != "DA ABBINARE":
                                return val
                            return riga['Destinazione_FTC']
                        df_source['Destinazione_FTC'] = df_source.apply(applica_mappa, axis=1)
                        st.success("✅ Mappatura recuperata!")
                except Exception as ex:
                    st.warning(f"Info recupero: {ex}")

            # --- LAYOUT PRINCIPALE MODIFICATO ---
            # Prima era [1.6, 1], ora [1, 1] per dare più spazio all'albero
            col_map, col_tree = st.columns([1, 1])
            
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
                with st.container(height=600):
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
                            
                            # --- TITOLO DINAMICO CON TOTALE ---
                            # Il totale appare direttamente nella barra cliccabile
                            label_con_totale = f"{dest}   ➡️   € {sub:,.2f}"
                            
                            with st.expander(label_con_totale):
                                # Qui dentro solo i conti, niente titolo grosso
                                show_cols = [c_conto, c_desc, c_saldo]
                                st.dataframe(
                                    grp[show_cols], 
                                    hide_index=True, 
                                    use_container_width=True,
                                    column_config={
                                        c_saldo: st.column_config.NumberColumn("Importo", format="%.2f")
                                    }
                                )
                        
                        st.divider()
                        st.metric("TOTALE QUADRATURA", f"€ {tot_gen:,.2f}")
                    else:
                        st.info("Inizia ad abbinare i conti per vedere l'albero.")

            # --- EXPORT STILE 'SAS' ---
            def split_mapping(val):
                if val == "DA ABBINARE" or pd.isna(val): return "", ""
                parts = str(val).split(' - ', 1)
                return (parts[0], parts[1]) if len(parts) == 2 else (val, "")

            export_df = edited_df.copy()
            export_df[['Cod_distinte', 'Desc_distinte']] = export_df['Destinazione_FTC'].apply(
                lambda x: pd.Series(split_mapping(x))
            )
            
            rename_map = {
                c_conto: 'Cod contab',
                c_desc: 'Descrizione',
                'Cod_distinte': 'Cod distinte',
                'Desc_distinte': 'Descrizione distinte'
            }
            export_df = export_df.rename(columns=rename_map)
            
            final_cols = ['Cod contab', 'Descrizione', 'Cod distinte', 'Descrizione distinte']
            if c_saldo in export_df.columns:
                final_cols.append(c_saldo)
                
            export_df = export_df[final_cols]

            st.divider()
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                export_df.to_excel(writer, index=False, sheet_name='Foglio1')
                if not mapped_data.empty:
                    summary = mapped_data.groupby('Destinazione_FTC')[c_saldo].sum().reset_index()
                    summary.to_excel(writer, index=False, sheet_name='Sintetico')

            st.download_button(
                "📥 Scarica Excel (Formato SAS)",
                data=output.getvalue(),
                file_name="Export_SAS.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

        except Exception as e:
            st.error(f"Errore critico: {e}")

if __name__ == "__main__":
    main()
