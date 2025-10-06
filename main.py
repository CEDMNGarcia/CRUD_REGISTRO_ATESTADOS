import streamlit as st
import pandas as pd
import os
from datetime import datetime, timedelta
import google.generativeai as genai
from google.genai.errors import APIError 

# --- CONFIGURAÇÃO DE ARQUIVOS E API ---

try:
    # Tenta obter a chave da seção [secrets] do secrets.toml
    API_KEY = st.secrets["GEMINI_API_KEY"]
except KeyError:
    # Se a chave não for encontrada, exibe um erro e interrompe a execução
    st.error("ERRO: Chave 'GEMINI_API_KEY' não encontrada. Crie o arquivo .streamlit/secrets.toml.")
    st.stop()


DATA_FILE = 'atestados_registrados.csv' 
COLABORADORES_FILE = 'colaboradores.xlsx' # Arquivo de referência

# --- NOVAS COLUNAS: 'Tipo' e 'Motivo' adicionadas, 'Descricao_do_CID' removida ---
COLUMNS = [
    "Nome_do_Colaborador", "Data_de_Inicio", "Dias", 
    "Data_Final", "CID", "Tipo", "Motivo" 
]

# --- FUNÇÕES DE CARREGAMENTO DE DADOS ---

def load_data():
    """Carrega o DataFrame de ausências ou cria um novo."""
    expected_columns = COLUMNS
    
    if os.path.exists(DATA_FILE):
        try:
            df = pd.read_csv(DATA_FILE)
            
            # Mapeamento para correção de nomes de colunas antigas (garante compatibilidade)
            col_mapping = {
                'Nome do Colaborador': 'Nome_do_Colaborador',
                'Data de Início': 'Data_de_Inicio',
                'Data Final': 'Data_Final',
                'Descricao CID': 'Motivo',        
                'Descricao_CID': 'Motivo',        
                'Descricao_do_CID': 'Motivo',      # Mapeia descrição antiga para 'Motivo'
            }
            renomear = {k: v for k, v in col_mapping.items() if k in df.columns}
            df.rename(columns=renomear, inplace=True)
            
            # Lógica para registros antigos: Se tiver 'Motivo' mas não 'Tipo', assume 'Atestado'
            if 'Tipo' not in df.columns:
                 # Cria 'Tipo' e assume 'Atestado' se o CID não for vazio
                 df['Tipo'] = df['CID'].apply(lambda x: 'Atestado' if pd.notna(x) and x != '' else 'Atestado')
            
            if 'Motivo' not in df.columns:
                df['Motivo'] = ''
            if 'CID' not in df.columns:
                df['CID'] = ''

            # Reindexa para garantir a nova ordem e colunas esperadas
            df = df.reindex(columns=expected_columns, fill_value='')
            
            df['Data_de_Inicio'] = pd.to_datetime(df['Data_de_Inicio'], errors='coerce').dt.date
            df['Data_Final'] = pd.to_datetime(df['Data_Final'], errors='coerce').dt.date
            
            return df.dropna(subset=['Nome_do_Colaborador']).reset_index(drop=True)

        except Exception as e:
            st.warning(f"Erro ao ler o arquivo de dados ({e}). Criando um DataFrame vazio.")
            return pd.DataFrame(columns=expected_columns)
    
    else:
        return pd.DataFrame(columns=expected_columns)


@st.cache_data(ttl=3600)
def load_colaboradores():
    """Carrega a lista de colaboradores do arquivo XLSX."""
    if os.path.exists(COLABORADORES_FILE):
        try:
            df_colaboradores = pd.read_excel(COLABORADORES_FILE)
            if 'Nome_do_Colaborador' in df_colaboradores.columns:
                return sorted(df_colaboradores['Nome_do_Colaborador'].astype(str).unique().tolist())
            else:
                st.error(f"ERRO: O arquivo '{COLABORADORES_FILE}' deve conter uma coluna chamada 'Nome_do_Colaborador'.")
                return []
        except Exception as e:
            st.error(f"ERRO ao ler o arquivo de colaboradores XLSX: {e}. Verifique o formato do arquivo.")
            return []
    else:
        st.warning(f"AVISO: O arquivo de colaboradores '{COLABORADORES_FILE}' não foi encontrado. Adicione este arquivo para habilitar a busca de nomes.")
        return []

def save_data(df):
    """Salva o DataFrame no arquivo CSV."""
    df.to_csv(DATA_FILE, index=False)

if 'df_atestados' not in st.session_state:
    st.session_state.df_atestados = load_data()

# --- 2. FUNÇÕES DE LÓGICA E API ---

@st.cache_data(ttl=3600) 
def pesquisar_cid(codigo_cid):
    """Busca a descrição simplificada do CID via Gemini API."""
    codigo_cid = codigo_cid.strip().upper()
    if not codigo_cid:
        return "N/A - Nenhum CID fornecido."

    genai.configure(api_key=API_KEY)
    
    prompt = f"""
    Forneça uma descrição do código CID: {codigo_cid} usando APENAS termos simples, não técnicos e concisos.
    A resposta deve ser ideal para um registro administrativo.
    Se o código for inválido, responda apenas: 'CÓDIGO INVÁLIDO'.
    """
    try:
        model = genai.GenerativeModel("gemini-2.5-flash") 
        response = model.generate_content(prompt)
        descricao = response.text.strip()
        
        if "CÓDIGO INVÁLIDO" in descricao or "NÃO ENCONTRADO" in descricao:
            return f"Código não encontrado ou inválido."
            
        return descricao
            
    except APIError as e:
        return f"Erro na API do Gemini: Verifique sua chave e cota. Detalhe: {e}"
    except Exception as e:
        return f"Erro inesperado na pesquisa do CID: {e}"

def calcular_datas(data_inicio, dias):
    """Calcula a data final e de retorno."""
    if not isinstance(data_inicio, datetime):
           data_inicio = datetime.strptime(str(data_inicio), '%Y-%m-%d').date()
    
    data_final = data_inicio + timedelta(days=dias - 1)
    data_retorno = data_final + timedelta(days=1)
    return data_final, data_retorno

# --- 3. LÓGICA DO CRUD (Atualizada com a formatação solicitada) ---

def add_record(nome, data_inicio, dias, tipo, cid="", motivo_texto=""):
    """Adiciona um novo registro."""
    df = st.session_state.df_atestados.copy()
    
    data_final, data_retorno = calcular_datas(data_inicio, dias)
    
    descricao_final = ""
    cid_final = ""

    if tipo == 'Atestado':
        cid_final = cid
        with st.spinner(f"Consultando descrição para CID: {cid}..."):
            descricao_cid = pesquisar_cid(cid)
            # Motivo: FORMATO SOLICITADO: "[cid] - [descrição]"
            descricao_final = f"{cid} - {descricao_cid}" 
    elif tipo == 'Folga':
        # Motivo: Texto livre
        descricao_final = motivo_texto
        cid_final = ""
    elif tipo == 'Banco de Horas':
        # Motivo: Texto fixo
        descricao_final = "Compensação de Banco de Horas"
        cid_final = ""
    elif tipo == 'Falta':
        # Motivo: Texto fixo
        descricao_final = "Falta"
        cid_final = ""


    novo_registro = {
        'Nome_do_Colaborador': nome,
        'Data_de_Inicio': data_inicio.strftime('%Y-%m-%d'),
        'Dias': int(dias),
        'Data_Final': data_final.strftime('%Y-%m-%d'),
        'CID': cid_final,
        'Tipo': tipo, 
        'Motivo': descricao_final 
    }
    
    st.session_state.df_atestados = pd.concat([df, pd.DataFrame([novo_registro])], ignore_index=True)
    save_data(st.session_state.df_atestados)
    st.success(f"Registro de **{tipo}** para **{nome}** adicionado! Retorno: **{data_retorno.strftime('%d/%m/%Y')}**")
    st.cache_data.clear() 
    st.rerun()

def delete_record(index):
    """Exclui um registro pelo índice."""
    st.session_state.df_atestados = st.session_state.df_atestados.drop(index).reset_index(drop=True)
    save_data(st.session_state.df_atestados)
    st.success("Registro excluído com sucesso!")
    st.cache_data.clear()
    st.rerun()

def update_record(index, nome, data_inicio, dias, cid, tipo_original, motivo_original):
    """Atualiza um registro existente."""
    df = st.session_state.df_atestados.copy()

    data_final, data_retorno = calcular_datas(data_inicio, dias)
    
    new_motive = motivo_original
    cid_to_save = cid
    
    # Se for Atestado E o CID mudou, consulta o Gemini novamente para o Motivo
    if tipo_original == 'Atestado':
        if df.loc[index, 'CID'] != cid:
            with st.spinner(f"Consultando nova descrição para CID: {cid}..."):
                descricao_cid = pesquisar_cid(cid)
                # Motivo: FORMATO SOLICITADO: "[cid] - [descrição]"
                new_motive = f"{cid} - {descricao_cid}"
        cid_to_save = cid # Salva o CID fornecido
    else:
        # Para outros tipos, o CID é sempre limpo, mas mantemos o Motivo original
        cid_to_save = ""
        new_motive = motivo_original # Mantém o motivo original (Ex: "Compensação de Banco de Horas")


    df.loc[index, 'Nome_do_Colaborador'] = nome
    df.loc[index, 'Data_de_Inicio'] = data_inicio.strftime('%Y-%m-%d')
    df.loc[index, 'Dias'] = int(dias)
    df.loc[index, 'Data_Final'] = data_final.strftime('%Y-%m-%d')
    df.loc[index, 'CID'] = cid_to_save
    df.loc[index, 'Tipo'] = tipo_original # Tipo não é editável aqui
    df.loc[index, 'Motivo'] = new_motive 

    st.session_state.df_atestados = df
    save_data(st.session_state.df_atestados)
    st.success(f"Registro de **{nome}** atualizado! Retorno: **{data_retorno.strftime('%d/%m/%Y')}**")
    st.rerun()


# --- 4. INTERFACE STREAMLIT (REESTRUTURADA) ---

st.set_page_config(page_title="Cadastro de Ausências", layout="wide")
st.title("🏥 Sistema de Cadastro de Atestados e Ausências")
st.markdown("---")

# Definição das DUAS NOVAS ABAS PRINCIPAIS
tab_registros, tab_automacoes = st.tabs([
    "📊 Registros", 
    "⚙️ Automações"
])

# 4.1. Carrega a lista de colaboradores (uma vez)
nomes_colaboradores = load_colaboradores()


# =================================================================
# 1. ABA REGISTROS (Contém as abas antigas)
# =================================================================
with tab_registros:
    
    # NOVAS SUB-ABAS (Suas abas antigas)
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "🩺 Atestado (CID)", 
        "💸 Banco de Horas", 
        "🚫 Falta", 
        "🏖️ Folga", 
        "📋 Tabela Completa", 
        "🛠️ Gerenciar por Pessoa"
    ])

    # --- TAB 1 (Sub-aba): ATESTADO (CID) ---
    with tab1:
        st.header("Adicionar Atestado Médico")

        with st.form("new_record_atestado_form", clear_on_submit=True):
            
            if nomes_colaboradores:
                nome = st.selectbox(
                    "Selecione o Colaborador:", options=nomes_colaboradores, index=None, key="form1_nome_selectbox"
                )
            else:
                nome = st.text_input("Nome do Colaborador:", key="form1_nome_input").strip()
                
            
            col_d1, col_d2 = st.columns(2)
            with col_d1:
                data_inicio = st.date_input("Início do Afastamento:", key="form1_data_inicio")
            with col_d2:
                dias = st.number_input("Dias de Atestado:", min_value=1, value=1, step=1, key="form1_dias")
            
            cid = st.text_input("Código CID:", max_chars=10, key="form1_cid").upper().strip()

            if data_inicio and dias >= 1:
                data_f, data_r = calcular_datas(data_inicio, dias)
                st.info(f"📅 Data Final Calculada: **{data_f.strftime('%d/%m/%Y')}** | 🔙 Retorno: **{data_r.strftime('%d/%m/%Y')}**")

            submitted = st.form_submit_button("✅ Registrar Atestado")

            if submitted:
                nome_final = nome.strip() if nome else None
                if nome_final and cid:
                    add_record(nome_final, data_inicio, dias, tipo='Atestado', cid=cid)
                else:
                    st.error("Por favor, preencha o Nome do Colaborador e o Código CID.")


    # --- TAB 2 (Sub-aba): BANCO DE HORAS ---
    with tab2:
        st.header("Adicionar Compensação por Banco de Horas")
        
        with st.form("new_record_banco_form", clear_on_submit=True):
            
            if nomes_colaboradores:
                nome = st.selectbox(
                    "Selecione o Colaborador:", options=nomes_colaboradores, index=None, key="form2_nome_selectbox"
                )
            else:
                nome = st.text_input("Nome do Colaborador:", key="form2_nome_input").strip()
                
            
            col_d1, col_d2 = st.columns(2)
            with col_d1:
                data_inicio = st.date_input("Início da Folga:", key="form2_data_inicio")
            with col_d2:
                dias = st.number_input("Dias de Folga:", min_value=1, value=1, step=1, key="form2_dias")
            
            st.caption("O Motivo será registrado automaticamente como: **Compensação de Banco de Horas**")

            if data_inicio and dias >= 1:
                data_f, data_r = calcular_datas(data_inicio, dias)
                st.info(f"📅 Data Final Calculada: **{data_f.strftime('%d/%m/%Y')}** | 🔙 Retorno: **{data_r.strftime('%d/%m/%Y')}**")

            submitted = st.form_submit_button("✅ Registrar Banco de Horas")

            if submitted:
                nome_final = nome.strip() if nome else None
                if nome_final:
                    add_record(nome_final, data_inicio, dias, tipo='Banco de Horas')
                else:
                    st.error("Por favor, preencha o Nome do Colaborador.")


    # --- TAB 3 (Sub-aba): FALTA (Simples, sem Motivo) ---
    with tab3:
        st.header("Adicionar Falta Não Justificada")
        
        with st.form("new_record_falta_form_simple", clear_on_submit=True):
            
            if nomes_colaboradores:
                nome = st.selectbox(
                    "Selecione o Colaborador:", options=nomes_colaboradores, index=None, key="form3_nome_selectbox_falta"
                )
            else:
                nome = st.text_input("Nome do Colaborador:", key="form3_nome_input_falta").strip()
                
            
            col_d1, col_d2 = st.columns(2)
            with col_d1:
                data_inicio = st.date_input("Início da Falta:", key="form3_data_inicio_falta")
            with col_d2:
                dias = st.number_input("Dias de Falta:", min_value=1, value=1, step=1, key="form3_dias_falta")
            
            st.caption("O Motivo será registrado automaticamente como: **Falta**")
            
            if data_inicio and dias >= 1:
                data_f, data_r = calcular_datas(data_inicio, dias)
                st.info(f"📅 Data Final Calculada: **{data_f.strftime('%d/%m/%Y')}** | 🔙 Retorno: **{data_r.strftime('%d/%m/%Y')}**")

            submitted = st.form_submit_button("✅ Registrar Falta")

            if submitted:
                nome_final = nome.strip() if nome else None
                if nome_final:
                    # Chama add_record com tipo='Falta' (motivo_texto é ignorado, Motivo fixo "Falta")
                    add_record(nome_final, data_inicio, dias, tipo='Falta') 
                else:
                    st.error("Por favor, preencha o Nome do Colaborador.")


    # --- TAB 4 (Sub-aba): FOLGA (Livre, com Motivo Obrigatório) ---
    with tab4:
        st.header("Adicionar Folga Programada (Abono, Acompanhamento, etc.)")
        
        with st.form("new_record_folga_form_motivo", clear_on_submit=True):
            
            if nomes_colaboradores:
                nome = st.selectbox(
                    "Selecione o Colaborador:", options=nomes_colaboradores, index=None, key="form4_nome_selectbox_folga"
                )
            else:
                nome = st.text_input("Nome do Colaborador:", key="form4_nome_input_folga").strip()
                
            
            col_d1, col_d2 = st.columns(2)
            with col_d1:
                data_inicio = st.date_input("Início da Folga:", key="form4_data_inicio_folga")
            with col_d2:
                dias = st.number_input("Dias de Folga:", min_value=1, value=1, step=1, key="form4_dias_folga")
                
            # Campo de Motivo Livre (SEMPRE ATIVO AQUI)
            motivo_livre = st.text_input(
                "Motivo da Folga (Ex: 'Abono de feriado', 'Acompanhamento médico do filho'):", 
                key="form4_motivo_input"
            ).strip()


            if data_inicio and dias >= 1:
                data_f, data_r = calcular_datas(data_inicio, dias)
                st.info(f"📅 Data Final Calculada: **{data_f.strftime('%d/%m/%Y')}** | 🔙 Retorno: **{data_r.strftime('%d/%m/%Y')}**")

            submitted = st.form_submit_button("✅ Registrar Folga")

            if submitted:
                nome_final = nome.strip() if nome else None
                
                if not motivo_livre:
                    st.error("Por favor, preencha o Motivo da Folga.")
                elif nome_final:
                    # Chama add_record com tipo='Folga' e o motivo_livre
                    add_record(nome_final, data_inicio, dias, tipo='Folga', motivo_texto=motivo_livre)
                else:
                    st.error("Por favor, preencha o Nome do Colaborador.")


    # --- TAB 5 (Sub-aba): TABELA COMPLETA (Visualização e Download) ---
    with tab5:
        st.header("Tabela Completa de Registros")
        
        df = st.session_state.df_atestados
        if df.empty:
            st.info("Nenhum registro encontrado.")
        else:
            # Prepara o DataFrame para exibição
            df_display = df.copy()
            
            # PONTO CRÍTICO: CONVERSÃO ROBUSTA PARA ORDENAÇÃO
            # Cria uma coluna de data/hora para ordenação (datetime64[ns])
            df_display['Data_para_Ordenar'] = pd.to_datetime(df_display['Data_de_Inicio'], errors='coerce')
            
            # ORDENAÇÃO: mais recente primeiro
            df_display_sorted = df_display.sort_values(
                by="Data_para_Ordenar", 
                ascending=False, 
                na_position='last' 
            )
            
            # --- CÁLCULO E FORMATAÇÃO PARA EXIBIÇÃO ---
            df_display_sorted['Data_de_Inicio'] = df_display_sorted['Data_para_Ordenar'].dt.date
            df_display_sorted['Data_Final'] = pd.to_datetime(df_display_sorted['Data_Final'], errors='coerce').dt.date
            df_display_sorted['Data_de_Retorno'] = df_display_sorted['Data_Final'] + timedelta(days=1)
            
            # Criar as colunas de string formatadas para exibição
            df_display_sorted['Início'] = df_display_sorted['Data_de_Inicio'].apply(lambda x: x.strftime('%d/%m/%Y') if not pd.isna(x) else '')
            df_display_sorted['Término'] = df_display_sorted['Data_Final'].apply(lambda x: x.strftime('%d/%m/%Y') if not pd.isna(x) else '')
            df_display_sorted['Retorno'] = df_display_sorted['Data_de_Retorno'].apply(lambda x: x.strftime('%d/%m/%Y') if not pd.isna(x) else '')
            
            # Seleciona as colunas finais para exibição (com Tipo e Motivo)
            df_table = df_display_sorted[['Nome_do_Colaborador', 'Tipo', 'Motivo', 'Início', 'Dias', 'Término', 'Retorno', 'CID']]

            st.dataframe(
                df_table, 
                hide_index=True, 
                use_container_width=True
            )

            st.markdown("---")

            # Botão de Download (XLSX)
            output = pd.io.common.BytesIO()
            df_table.to_excel(output, index=False, engine='openpyxl')
            xlsx_data = output.getvalue()
            
            st.download_button(
                label="⬇️ Baixar Planilha de Registros (XLSX)",
                data=xlsx_data,
                file_name='registros_ausencias.xlsx',
                mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                key='download_xlsx_button_tab5'
            )

    # --- TAB 6 (Sub-aba): GERENCIAR POR PESSOA (Agrupamento e Edição) ---
    with tab6:
        st.header("🛠️ Gerenciar Atestados e Ausências por Colaborador")

        df = st.session_state.df_atestados
        if df.empty:
            st.info("Nenhum registro encontrado. Adicione nas abas anteriores.")
        else:
            st.markdown("Clique no nome da pessoa para ver e editar **todos os registros** dela.")
            
            df_display = df.copy()
            
            df_display['Data_de_Inicio'] = pd.to_datetime(df_display['Data_de_Inicio'], errors='coerce').dt.date
            df_display['Data_Final'] = pd.to_datetime(df_display['Data_Final'], errors='coerce').dt.date
            df_display['Data_de_Retorno'] = df_display['Data_Final'] + timedelta(days=1)
            
            registros_agrupados = df_display.groupby('Nome_do_Colaborador')

            # Itera sobre os grupos (cada pessoa)
            for nome_colaborador, df_grupo in registros_agrupados:
                
                num_registros = len(df_grupo)
                ultima_data = df_grupo['Data_Final'].max()
                ultimo_registro = ultima_data.strftime('%d/%m/%Y') if not pd.isna(ultima_data) else "N/A"
                
                # Título do Expander (Card da Pessoa)
                title = f"👤 **{nome_colaborador}** ({num_registros} Registros) | Último: {ultimo_registro}"
                
                with st.expander(title):
                    st.subheader(f"Lista de Registros para {nome_colaborador}")
                    
                    # Itera sobre os atestados daquela pessoa (cada linha do grupo)
                    for index, row in df_grupo.iterrows():
                        
                        # Título do Popover ajustado para mostrar o Tipo e Motivo
                        motivo_curto = row['Motivo'][:30] + '...' if len(row['Motivo']) > 30 else row['Motivo']
                        title_popover = f"🗓️ {row['Tipo']} de {row['Data_de_Inicio'].strftime('%d/%m/%Y')} - {row['Dias']} dias ({motivo_curto})"
                        
                        with st.popover(title_popover, use_container_width=True):
                            st.subheader(f"Editar Registro ID: {index}")
                            st.markdown(f"**Tipo:** {row['Tipo']} | **Motivo:** {row['Motivo']}")
                            st.markdown(f"**Retorno ao Trabalho:** {row['Data_de_Retorno'].strftime('%d/%m/%Y')}")

                            # 1. Formulário de Edição (Usa st.form_submit_button)
                            with st.form(f"edit_form_{index}", clear_on_submit=False):
                                
                                st.text_input("Colaborador", value=row["Nome_do_Colaborador"], key=f"edit_nome_{index}", disabled=True) 
                                
                                col_e1, col_e2 = st.columns(2)

                                with col_e1:
                                    edited_data_inicio = st.date_input("Início da Ausência", value=row["Data_de_Inicio"], key=f"edit_data_inicio_{index}")
                                    
                                    # CID SÓ É EDITÁVEL SE O TIPO FOR ATESTADO
                                    cid_value = row["CID"] if row['CID'] else ""
                                    edited_cid = st.text_input(
                                        "Código CID (Apenas para Atestado)", 
                                        value=cid_value, max_chars=10, 
                                        key=f"edit_cid_{index}", 
                                        disabled=(row['Tipo'] != 'Atestado') # Desabilita se não for Atestado
                                    ).upper().strip()
                                    
                                with col_e2:
                                    edited_dias = st.number_input("Dias de Ausência", min_value=1, value=int(row["Dias"]), step=1, key=f"edit_dias_{index}")
                                    
                                    if edited_data_inicio and edited_dias >= 1:
                                        data_f, data_r = calcular_datas(edited_data_inicio, edited_dias)
                                        st.caption(f"Nova Data Final: {data_f.strftime('%d/%m/%Y')} | Novo Retorno: {data_r.strftime('%d/%m/%Y')}")

                                
                                submit_edit = st.form_submit_button("💾 Salvar Edição", type="primary")

                                if submit_edit:
                                    update_record(index, row["Nome_do_Colaborador"], edited_data_inicio, edited_dias, edited_cid, row['Tipo'], row['Motivo'])
                            
                            st.markdown("---")
                            
                            # 2. Formulário de Exclusão (Mini-Formulário Isolado)
                            with st.form(f"delete_form_{index}", clear_on_submit=True):
                                st.warning("Atenção: A exclusão deste registro é irreversível.")
                                
                                delete_submitted = st.form_submit_button(
                                    "❌ EXCLUIR REGISTRO", 
                                    help="Esta ação é irreversível.", 
                                    type="secondary"
                                )

                                if delete_submitted:
                                    delete_record(index)


# =================================================================
# 2. ABA AUTOMAÇÕES (Nova aba para ferramentas)
# =================================================================
with tab_automacoes:
    st.header("Upload de Arquivos para Automação")
    st.markdown("Use esta ferramenta para carregar planilhas e processar novos dados.")
    
    # Bloco para Upload/Arrastar Arquivo
    uploaded_file = st.file_uploader(
        "Carregue ou arraste seu arquivo aqui (.csv, .xlsx)",
        type=['csv', 'xlsx'],
        accept_multiple_files=False
    )

    if uploaded_file is not None:
        file_details = {"FileName": uploaded_file.name, "FileType": uploaded_file.type}
        st.success(f"Arquivo carregado com sucesso: **{file_details['FileName']}**")
        st.info("Aqui a lógica de processamento do arquivo será adicionada (leitura de dados, validação, etc.).")
        
    else:
        st.info("Aguardando um arquivo para processamento...")