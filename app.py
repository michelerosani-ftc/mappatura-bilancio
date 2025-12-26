import streamlit as st
import pandas as pd
import io
import os

# --- CONFIGURAZIONE ---
st.set_page_config(page_title="Mappatura Bilancio PRO", layout="wide")
DEFAULT_SCHEMA_FILENAME = "schema_ftc.xlsx"

# CSS PERSONALIZZATO
st.markdown("""
<style>
    .streamlit-expanderHeader { font-size: 14px !important; padding: 5px !important; }
    div[data-testid="stDataFrame"] { font-size: 13px !important; }
</style>
""", unsafe_allow_html=True)

# --- FUNZIONI DI LETTURA INTELLIGENTE (SMART LOAD) ---

@st.cache_data
def load_excel_smart(uploaded_file):
    """
    Legge il file Excel cercando automaticamente la riga di intestazione corretta.
    Risolve il problema dei file che hanno righe vuote o metadati all'inizio.
    """
    if uploaded_file is None:
        return None
    
    try:
        # 1. Legge solo le prime 15 righe senza intestazione per ispezionare
        df_preview = pd.read_excel(uploaded_file, header=None, nrows=15)
        
        header_idx = 0
        found = False
        
        # 2. Cerca la riga che contiene parole chiave tipiche dell'intestazione
        for i, row in df_preview.iterrows():
            row_str = row.astype(str).str.lower().values
            # Parole chiave da cercare (aggiunto 'cod contab' per i file SAS/Export)
            if any(x in row_str for x in ['cod contab', 'conto', 'mastro', 'descrizione']):
                header_idx = i
                found = True
                break
        
        # 3. Ricarica il file intero usando l'indice trovato
        uploaded_file.seek(0) # Riavvolge il file
        df = pd.read_excel(uploaded_file, header=header_idx)
        return df

    except Exception as e:
        st.error(f"Errore nella lettura del file: {e}")
        return None

@st.cache_data
def load_default_schema():
    if os.path.exists(DEFAULT_SCHEMA_FILENAME):
        try:
            return pd.read_excel(DEFAULT_SCHEMA_FILENAME)
        except:
            return None
    return None

# -------------------------------------------

def main():
    st.title("📊 Mappatura Bilancio Avanzata")
    
    # --- 1. CONFIGURAZIONE ---
    st.sidebar.header("1. Configurazione")
    
    df_schema = load_default_schema()
    
    if df_schema is None:
        uploaded_schema = st.sidebar.file_uploader("Carica Piano Conti FTC", type=['xlsx'])
        if uploaded_schema:
            df_schema = pd.read_excel(uploaded_schema)
    else:
        st.sidebar.success("✅ Schema FTC caricato")

    if df_schema is None:
        st.warning(f"Carica lo schema FTC per iniziare.")
        st.stop() 

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
        source_file = st.file_uploader("Carica Excel (Origine)", type=['xlsx'], key="src")
        
    with col2:
        st.subheader("B. Recupera Lavoro (Mappatura)")
        mapping_file = st.file_uploader("Carica file precedente", type=['xlsx'], key="map")

    if source_file:
        try:
            # --- LETTURA SOURCE INTELLIGENTE ---
            # Usa la nuova funzione che trova l'intestazione giusta
            df_source = load_excel_smart(source_file)
            
            if df_source is not None:
                df_source = df_source.copy()
                df_source.columns = df_source.columns.str.strip()
                
                # --- RICONOSCIMENTO COLONNE ---
                cols = df_source.columns
                
                # Cerca colonne in modo flessibile
                c_conto = next((c for c in cols if 'conto' in c.lower() or 'cod contab' in c.lower()), None)
                if not c_conto: c_conto = cols[0] 
                
                c_desc = next((c for c in cols if 'desc' in c.lower()), None)
                if not c_desc: c_desc = cols[1] 

                # Cerca Saldo
                saldo_candidates = [c for c in cols if 'saldo' in c.lower() or 'imp' in c.lower()]
                c_saldo = None
                for cand in saldo_candidates:
                    if 'fin' in cand.lower() or 'chiu' in cand.lower():
                        c_saldo = cand
                        break
                if c_saldo is None and saldo_candidates: c_saldo = saldo_candidates[-1]
                if c_saldo is None: c_saldo = cols[-1]

                # --- PULIZIA DATI ---
                rows_orig = len(df_source)
                df_source[c_conto] = df_source[c_conto].astype(str).str.strip()
                
                # 1. Gestione Eccezioni (14 e 40)
                target_14 = ['14/0000/0000', '14/00000000', '1400000000']
                target_40 = ['40/0000/0000', '40/00000000', '4000000000']
                df_source.loc[df_source[c_conto].isin(target_14), c_conto] = '14/0000/0001'
                df_source.loc[df_source[c_conto].isin(target_40), c_conto] = '40/0000/0001'
                
                # 2. Rimozione righe che finiscono con 0000
                df_source = df_source[~df_source[c_conto].str.endswith('0000')]
                
                # 3. Rimozione righe vuote
                df_source = df_source[df_source[c_conto] != 'nan']
                df_source = df_source.dropna(subset=[c_saldo])
                
                # 4. Nascondi colonne inutili
                cols_to_drop = [c for c in df_source.columns if any(x in c.lower() for x in ['dare', 'avere', 'apertura'])]
                if c_saldo in cols_to_drop: cols_to_drop.remove(c_saldo)
                if cols_to_drop: df_source = df_source.drop(columns=cols_to_drop)

                st.caption(f"Righe caricate: **{len(df_source)}** (da {rows_orig}). Colonne rilevate: {c_conto} | {c_saldo}")
                st.divider()

                # --- RECUPERO MAPPATURA ---
                if 'Destinazione_FTC' not in df_source.columns:
                    df_source['Destinazione_FTC'] = "DA ABBINARE"

                if mapping_file:
                    try:
                        # Anche il file di mapping lo carichiamo "smart"
                        df_old = load_excel_smart(mapping_file)
                        
                        if df_old is not None:
                            old_cols = df_old.columns
                            k_conto = next((c for c in old_cols if 'cod' in c.lower() and 'contab' in c.lower()), None)
                            if not k_conto: k_conto = next((c for c in old_cols if 'conto' in c.lower()), None)
                            
                            mappa_dict = {}
                            if k_conto:
                                # Caso file SAS Export
                                if 'Cod distinte' in old_cols and 'Descrizione distinte' in old_cols:
                                    codici = df_old['Cod distinte'].astype(str)
                                    descri = df_old['Descrizione distinte'].astype(str)
                                    full_dest = codici + " - " + descri
                                    mappa_dict = pd.Series(full_dest.values, index=df_old[k_conto].astype(str)).to_dict()
                                # Caso file Standard
                                elif 'Destinazione_FTC' in old_cols:
                                    mappa_dict = pd.Series(df_old['Destinazione_FTC'].values, index=df_old[k_conto].astype(str)).to_dict()
                            
                            if mappa_dict:
                                conti_series = df_source[c_conto].astype(str)
                                nuovi_valori = conti_series.map(mappa_dict)
                                mask = (nuovi_valori.notna()) & (~nuovi_valori.astype(str).str.contains("nan -")) & (nuovi_valori != "DA ABBINARE")
                                df_source.loc[mask, 'Destinazione_FTC'] = nuovi_valori[mask]
                                st.success(f"✅ Mappatura recuperata! ({mask.sum()} conti abbinati)")
                    except Exception as ex:
                        st.warning(f"Info recupero: {ex}")

                # --- LAYOUT PRINCIPALE ---
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
                                
                                color = "green" if sub >= 0 else "red"
                                label_con_totale = f"{dest}   ➡️   € {sub:,.2f}"
                                
                                with st.expander(label_con_totale):
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

                # --- EXPORT ---
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
