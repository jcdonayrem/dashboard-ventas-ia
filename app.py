import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import requests
import json
import os
from google import genai
from supabase import create_client, Client

# Configuración de la página de Streamlit
st.set_page_config(
    page_title="Dashboard de Ventas IA",
    page_icon="📊",
    layout="wide"
)

st.title("📊 Dashboard de Ventas IA")

# 1. Lectura de Credenciales de Supabase desde st.secrets
def get_supabase_credentials():
    url = None
    key = None

    # Intentar obtener de la raíz de st.secrets
    try:
        url = st.secrets.get("SUPABASE_URL") or st.secrets.get("supabase_url")
        key = st.secrets.get("SUPABASE_KEY") or st.secrets.get("supabase_key")
    except Exception:
        pass

    # Intentar obtener desde una sección específica [supabase]
    if not url or not key:
        try:
            if "supabase" in st.secrets:
                sub_sec = st.secrets["supabase"]
                if hasattr(sub_sec, "get"):
                    if not url:
                        url = sub_sec.get("url") or sub_sec.get("SUPABASE_URL") or sub_sec.get("supabase_url")
                    if not key:
                        key = sub_sec.get("key") or sub_sec.get("SUPABASE_KEY") or sub_sec.get("supabase_key")
                elif isinstance(sub_sec, dict):
                    if not url:
                        url = sub_sec.get("url") or sub_sec.get("SUPABASE_URL")
                    if not key:
                        key = sub_sec.get("key") or sub_sec.get("SUPABASE_KEY")
        except Exception:
            pass

    return url, key

supabase_url, supabase_key = get_supabase_credentials()

# Mostrar error explícito en pantalla si faltan credenciales
if not supabase_url or not supabase_key:
    st.error("""
    ❌ **Error de Configuración**: No se encontraron las credenciales de Supabase en `st.secrets`.

    Por favor, asegúrate de configurar las variables `SUPABASE_URL` y `SUPABASE_KEY` (o dentro de una sección `[supabase]`) en los Secrets de Streamlit.
    """)
    st.stop()

# 2. Inicialización del Cliente de Supabase
@st.cache_resource
def init_supabase(url, key):
    try:
        return create_client(url, key)
    except Exception as e:
        st.error(f"❌ **Error al inicializar el cliente de Supabase**: {e}")
        st.stop()

client = init_supabase(supabase_url, supabase_key)

# 3. Funciones de Aplanamiento y Carga de Datos Relacionales (Sin Fallback)
def flatten_sales(data):
    """Aplatana el JSON resultante de ventas de modelo relacional."""
    records = []
    for row in data:
        prod = row.get("productos") or {}
        chan = row.get("canales") or {}
        reg = row.get("regiones") or {}

        if isinstance(prod, list) and len(prod) > 0:
            prod = prod[0]
        if isinstance(chan, list) and len(chan) > 0:
            chan = chan[0]
        if isinstance(reg, list) and len(reg) > 0:
            reg = reg[0]

        record = {
            "id": row.get("id"),
            "fecha": row.get("fecha"),
            "cantidad": row.get("cantidad"),
            "precio_unitario_venta": row.get("precio_unitario_venta"),
            "descuento_aplicado": row.get("descuento_aplicado"),
            "ventas": float(row.get("monto_total") or 0.0),
            "region_id": row.get("region_id"),
            "canal_id": row.get("canal_id"),
            "promocion_id": row.get("promocion_id"),
            "producto": prod.get("nombre") or "Desconocido",
            "categoria": prod.get("categoria") or "Sin Categoría",
            "canal": chan.get("nombre") or "Desconocido",
            "region": reg.get("nombre") or "Desconocido"
        }
        records.append(record)
    df = pd.DataFrame(records)
    if not df.empty and 'fecha' in df.columns:
        df['fecha'] = pd.to_datetime(df['fecha'])
    return df

def flatten_budget(data):
    """Aplatana el JSON resultante de presupuestos utilizando anio y mes."""
    records = []
    for row in data:
        record = {
            "id": row.get("id"),
            "anio": row.get("anio"),
            "mes": row.get("mes"),
            "presupuesto": float(row.get("monto_presupuestado") or 0.0),
            "region_id": row.get("region_id"),
            "canal_id": row.get("canal_id")
        }
        records.append(record)

    df = pd.DataFrame(records)
    if not df.empty:
        # Crear la columna sintética fecha combinando anio y mes
        df['fecha'] = pd.to_datetime(
            df['anio'].astype(str) + '-' + df['mes'].astype(str).str.zfill(2) + '-01'
        )
    return df

@st.cache_data
def load_all_data():
    """Consulta la tabla ventas y presupuestos con sus relaciones directas de dimensiones."""
    df_sales = None
    df_budget = None

    # Consulta Principal de Ventas (incluyendo descuento_aplicado y promocion_id)
    try:
        sales_resp = client.table("ventas").select(
            "id, fecha, cantidad, precio_unitario_venta, descuento_aplicado, monto_total, "
            "region_id, canal_id, promocion_id, "
            "productos(nombre, categoria), "
            "canales(nombre), "
            "regiones(nombre)"
        ).execute()
        if sales_resp.data:
            df_sales = flatten_sales(sales_resp.data)
    except Exception as e:
        st.error(f"❌ **Error al consultar la tabla 'ventas'**: {e}")
        st.stop()

    # Consulta de Presupuestos adaptada al esquema real
    try:
        budget_resp = client.table("presupuestos").select(
            "id, anio, mes, monto_presupuestado, region_id, canal_id"
        ).execute()
        if budget_resp.data:
            df_budget = flatten_budget(budget_resp.data)
    except Exception as e:
        st.error(f"❌ **Error al consultar la tabla 'presupuestos'**: {e}")
        st.stop()

    if df_sales is None or df_sales.empty:
        st.error("❌ **Error de Datos**: No se pudieron obtener registros válidos de la tabla 'ventas'.")
        st.stop()

    # Conversión explícita y segura a numérico de descuento_aplicado rellenando nulos con cero
    df_sales['descuento_aplicado'] = pd.to_numeric(df_sales['descuento_aplicado'], errors='coerce').fillna(0)

    if df_budget is None:
        df_budget = pd.DataFrame(columns=["id", "fecha", "presupuesto", "canal_id", "region_id"])

    # Mapeo de nombres de canal y región en presupuestos a partir de las ventas
    if not df_budget.empty:
        region_map = dict(zip(df_sales['region_id'].dropna(), df_sales['region'].dropna()))
        canal_map = dict(zip(df_sales['canal_id'].dropna(), df_sales['canal'].dropna()))

        df_budget['region'] = df_budget['region_id'].map(region_map).fillna("Desconocido")
        df_budget['canal'] = df_budget['canal_id'].map(canal_map).fillna("Desconocido")
    else:
        df_budget['region'] = pd.Series(dtype=str)
        df_budget['canal'] = pd.Series(dtype=str)

    return df_sales, df_budget

# Cargar los datos directamente desde PostgreSQL (Sin Fallback)
df_sales, df_budget = load_all_data()

# 4. Formateadores auxiliares para monedas y números con abreviaciones
def format_currency_short(value):
    """Abrevia cifras grandes para evitar que el texto se corte."""
    if value >= 1_000_000:
        return f"${value / 1_000_000:,.2f}M"
    elif value >= 1_000:
        return f"${value / 1_000:,.2f}K"
    else:
        return f"${value:,.2f}"

def format_currency_full(value):
    return f"${value:,.2f}"

def format_number(value):
    return f"{value:,}"

# 5. Estructura de Pestañas Principales
tab_dashboard, tab_copilot, tab_whatif = st.tabs([
    "📊 Dashboard Analytics",
    "💬 Copiloto IA (Text-to-SQL)",
    "🔮 Simulaciones What-If"
])

# ==================== PESTAÑA 1: DASHBOARD ANALYTICS ====================
with tab_dashboard:
    # Barra Lateral (Sidebar) de Filtros específica para el Dashboard
    st.sidebar.header("Filtros de Datos")
    st.sidebar.success("⚡ Conectado a Supabase PostgreSQL")

    # Filtro de Rango de Fechas (por defecto abarcando todo el periodo disponible en ventas)
    min_date = df_sales['fecha'].min().date()
    max_date = df_sales['fecha'].max().date()

    date_range = st.sidebar.date_input(
        "Selecciona Rango de Fechas",
        value=(min_date, max_date),
        min_value=min_date,
        max_value=max_date
    )

    # Control robusto para rango de fechas incompleto durante selección del usuario
    if isinstance(date_range, tuple) and len(date_range) == 2:
        start_date, end_date = date_range
    else:
        start_date = date_range[0] if isinstance(date_range, (list, tuple)) else date_range
        end_date = start_date

    # Selección múltiple por Región
    all_regions = sorted(df_sales['region'].unique().tolist())
    selected_regions = st.sidebar.multiselect(
        "Región",
        options=all_regions,
        default=all_regions
    )

    # Selección múltiple por Canal de Venta
    all_channels = sorted(df_sales['canal'].unique().tolist())
    selected_channels = st.sidebar.multiselect(
        "Canal de Venta",
        options=all_channels,
        default=all_channels
    )

    # Aplicar Filtros a Ventas y Presupuestos
    start_dt = pd.to_datetime(start_date)
    end_dt = pd.to_datetime(end_date)

    filtered_sales = df_sales[
        (df_sales['fecha'] >= start_dt) &
        (df_sales['fecha'] <= end_dt) &
        (df_sales['region'].isin(selected_regions)) &
        (df_sales['canal'].isin(selected_channels))
    ]

    filtered_budget = df_budget[
        (df_budget['fecha'] >= start_dt) &
        (df_budget['fecha'] <= end_dt) &
        (df_budget['region'].isin(selected_regions)) &
        (df_budget['canal'].isin(selected_channels))
    ] if not df_budget.empty else pd.DataFrame(columns=df_budget.columns)

    # Manejo de estados de 0 resultados y visualizaciones
    if filtered_sales.empty:
        st.warning("⚠️ No hay resultados disponibles para los filtros seleccionados. Por favor, ajusta los criterios en la barra lateral.")

        # Tarjetas de KPIs vacías
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Ventas Totales", "$0.00")
        with col2:
            st.metric("Total de Transacciones", "0")
        with col3:
            st.metric("Ticket Promedio", "$0.00")
        with col4:
            st.metric("Descuentos Aplicados", "$0.00")
    else:
        # Cálculos de Métricas KPIs
        total_sales = filtered_sales['ventas'].sum()
        total_transactions = len(filtered_sales)
        avg_ticket = filtered_sales['ventas'].mean() if total_transactions > 0 else 0
        total_discounts = filtered_sales['descuento_aplicado'].sum()

        # Mostrar Tarjetas de KPIs con st.metric
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Ventas Totales", format_currency_short(total_sales), help=format_currency_full(total_sales))
        with col2:
            st.metric("Total de Transacciones", format_number(total_transactions))
        with col3:
            st.metric("Ticket Promedio", format_currency_full(avg_ticket))
        with col4:
            st.metric("Descuentos Aplicados", format_currency_short(total_discounts), help=format_currency_full(total_discounts))

        st.markdown("---")

        # Layout y Diseño: Cuadrícula de 2 columnas equilibrada
        row1_left, row1_right = st.columns(2)

        with row1_left:
            # Gráfico de Líneas: Tendencia de ventas mensual vs. Presupuesto (Budget)
            sales_monthly = filtered_sales.copy()
            sales_monthly['Mes'] = sales_monthly['fecha'].dt.strftime('%Y-%m')
            sales_grouped = sales_monthly['ventas'].groupby(sales_monthly['Mes']).sum().reset_index()

            if not filtered_budget.empty:
                budget_monthly = filtered_budget.copy()
                budget_monthly['Mes'] = budget_monthly['fecha'].dt.strftime('%Y-%m')
                budget_grouped = budget_monthly['presupuesto'].groupby(budget_monthly['Mes']).sum().reset_index()
            else:
                budget_grouped = pd.DataFrame(columns=['Mes', 'presupuesto'])

            # Combinar Ventas y Presupuesto por Mes
            merged_trend = pd.merge(sales_grouped, budget_grouped, on='Mes', how='outer').fillna(0)
            merged_trend = merged_trend.sort_values('Mes')

            fig_line = px.line(
                merged_trend,
                x='Mes',
                y=['ventas', 'presupuesto'],
                labels={'value': 'Monto ($)', 'variable': 'Métrica', 'Mes': 'Mes'},
                title='Tendencia de Ventas Mensual vs. Presupuesto (Budget)',
                markers=True
            )

            new_names = {'ventas': 'Ventas Reales', 'presupuesto': 'Presupuesto'}
            fig_line.for_each_trace(lambda t: t.update(name = new_names.get(t.name, t.name)))

            fig_line.update_layout(
                hovermode="x unified",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
            )
            fig_line.update_traces(
                hovertemplate="Monto: $%{y:,.2f}"
            )
            st.plotly_chart(fig_line, use_container_width=True)

        with row1_right:
            # Gráfico de Dona: Distribución de Ventas por Canal
            canal_grouped = filtered_sales.groupby('canal')['ventas'].sum().reset_index()
            fig_pie = px.pie(
                canal_grouped,
                names='canal',
                values='ventas',
                title='Distribución de Ventas por Canal (Ingresos %)',
                hole=0.4,
                color_discrete_sequence=px.colors.qualitative.Pastel
            )
            fig_pie.update_traces(
                textinfo='percent+label',
                hovertemplate="<b>%{label}</b><br>Ventas: $%{value:,.2f}<br>Porcentaje: %{percent}"
            )
            st.plotly_chart(fig_pie, use_container_width=True)

        st.markdown("---")

        row2_left, row2_right = st.columns(2)

        with row2_left:
            # Gráfico de Barras Horizontales: Ventas Totales por Región
            region_grouped = filtered_sales.groupby('region')['ventas'].sum().reset_index()
            fig_region = px.bar(
                region_grouped,
                x='ventas',
                y='region',
                orientation='h',
                labels={'ventas': 'Ventas Totales ($)', 'region': 'Región'},
                title='Ventas Totales por Región',
                color='ventas',
                color_continuous_scale='blues'
            )
            fig_region.update_layout(
                yaxis={'categoryorder': 'total ascending'},
                coloraxis_showscale=False
            )
            fig_region.update_traces(
                hovertemplate="<b>%{y}</b><br>Ventas: $%{x:,.2f}"
            )
            st.plotly_chart(fig_region, use_container_width=True)

        with row2_right:
            # Gráfico de Barras: Top 5 de productos más vendidos en el periodo seleccionado
            product_grouped = filtered_sales.groupby('producto')['ventas'].sum().reset_index()
            top_products = product_grouped.sort_values('ventas', ascending=False).head(5)

            fig_bar = px.bar(
                top_products,
                x='ventas',
                y='producto',
                orientation='h',
                labels={'ventas': 'Ventas Totales ($)', 'producto': 'Producto'},
                title='Top 5 Productos más Vendidos',
                color='ventas',
                color_continuous_scale='blues'
            )
            fig_bar.update_layout(
                yaxis={'categoryorder': 'total ascending'},
                coloraxis_showscale=False
            )
            fig_bar.update_traces(
                hovertemplate="<b>%{y}</b><br>Ventas: $%{x:,.2f}"
            )
            st.plotly_chart(fig_bar, use_container_width=True)

        st.markdown("---")

        row3_left, row3_right = st.columns(2)

        with row3_left:
            # Gráfico de Barras: Desempeño de Promociones (Con vs Sin Promoción)
            promo_df = filtered_sales.copy()
            promo_df['Con Promoción'] = promo_df['promocion_id'].apply(
                lambda x: "Con Promoción" if pd.notna(x) and x != "" and str(x).lower() != "none" and x != 0 else "Sin Promoción"
            )
            promo_grouped = promo_df.groupby('Con Promoción')['ventas'].sum().reset_index()

            fig_promo = px.bar(
                promo_grouped,
                x='Con Promoción',
                y='ventas',
                labels={'ventas': 'Ventas Totales ($)', 'Con Promoción': 'Estado Promocional'},
                title='Desempeño de Ventas: Con vs. Sin Promoción',
                color='Con Promoción',
                color_discrete_map={"Con Promoción": "#1f77b4", "Sin Promoción": "#ff7f0e"}
            )
            fig_promo.update_traces(
                hovertemplate="<b>%{x}</b><br>Ventas: $%{y:,.2f}"
            )
            st.plotly_chart(fig_promo, use_container_width=True)

        with row3_right:
            st.subheader("Resumen de Métricas del Periodo")
            st.write("A continuación se muestra el desglose del rendimiento del periodo seleccionado para auditoría:")

            metrics_df = pd.DataFrame({
                "Métrica": ["Ventas Totales", "Transacciones", "Ticket Promedio", "Descuentos Totales"],
                "Valor": [format_currency_full(total_sales), format_number(total_transactions), format_currency_full(avg_ticket), format_currency_full(total_discounts)]
            })
            st.dataframe(metrics_df, hide_index=True, use_container_width=True)


# ==================== PESTAÑA 2: COPILOTO IA (TEXT-TO-SQL) ====================
with tab_copilot:
    st.header("💬 Copiloto IA (Text-to-SQL Chatbot)")
    st.write("Consulta la base de datos de ventas en lenguaje natural. Tu pregunta se traducirá automáticamente a PostgreSQL y se ejecutará en tiempo real.")

    # 1. Recuperación de Metadatos del Esquema de Supabase
    @st.cache_data(ttl=600)
    def get_schema_metadata():
        try:
            resp = client.table("metadatos_esquema").select("*").execute()
            if resp.data:
                meta_text = "Metadatos del Esquema de la Base de Datos Relacional:\n"
                for row in resp.data:
                    meta_text += f"\n- Tabla: {row.get('tabla') or row.get('nombre_tabla')}\n"
                    meta_text += f"  Descripción: {row.get('descripcion')}\n"
                    meta_text += f"  Columnas: {row.get('columnas')}\n"
                    reglas = row.get('reglas_negocio') or row.get('reglas')
                    if reglas:
                        meta_text += f"  Reglas de Negocio: {reglas}\n"
                return meta_text
        except Exception as e:
            st.sidebar.warning(f"No se pudieron cargar los metadatos del esquema: {e}")
        return "Esquema relacional estándar: tablas 'ventas', 'productos', 'regiones', 'canales', 'presupuestos'"

    # 2. Funciones de Llamada Directa a LLM (Gemini / OpenAI)
    def call_openai_api(prompt, system_prompt, api_key):
        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
        payload = {
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.0
        }
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    def generate_text_to_sql(prompt, metadata_str):
        # Buscar llaves en secrets y env
        openai_key = st.secrets.get("OPENAI_API_KEY") or os.environ.get("OPENAI_API_KEY")
        gemini_key = st.secrets.get("GEMINI_API_KEY") or st.secrets.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")

        if not gemini_key and not openai_key:
            raise Exception("No se configuraron las llaves de API (GEMINI_API_KEY u OPENAI_API_KEY) en los secrets para realizar la generación real de SQL.")

        system_prompt = f"""
        Eres un traductor experto de lenguaje natural a SQL para PostgreSQL.
        Tu única tarea es generar la consulta SQL que responda exactamente a la pregunta del usuario basándote en la estructura de base de datos relacional y sus reglas de negocio.

        Estructura de la base de datos y Metadatos:
        {metadata_str}

        IMPORTANTE:
        - Responde ÚNICAMENTE con la consulta SQL ejecutable.
        - No uses bloques de código Markdown (como ```sql o ```). Retorna solo texto plano.
        - Si de todas formas decides usar bloques Markdown, nos aseguraremos de limpiarlos, pero preferimos texto plano directo.
        - Asegúrate de respetar los nombres de tablas y columnas indicados en los metadatos.
        """

        if gemini_key:
            client_gemini = genai.Client(api_key=gemini_key)
            # En la API oficial moderna genai.Client, las instrucciones del sistema se pasan como config.
            # Sin embargo, para mayor robustez ante diferentes versiones/configuraciones, se añade también en el contexto del prompt.
            config = {
                "system_instruction": system_prompt,
                "temperature": 0.0
            }
            try:
                response = client_gemini.models.generate_content(
                    model="gemini-2.0-flash",
                    contents=prompt,
                    config=config
                )
            except Exception:
                # Fallback si por alguna razón falla el config object directo
                full_prompt = f"{system_prompt}\n\nPregunta del usuario:\n{prompt}"
                response = client_gemini.models.generate_content(
                    model="gemini-2.0-flash",
                    contents=full_prompt
                )
            response_text = response.text
        else:
            response_text = call_openai_api(prompt, system_prompt, openai_key)

        # Limpiar la respuesta adecuadamente (eliminar Markdown ```sql, etc.)
        sql = response_text.strip()
        if "```sql" in sql:
            sql = sql.split("```sql")[1].split("```")[0].strip()
        elif "```" in sql:
            sql = sql.split("```")[1].split("```")[0].strip()

        sql_clean = sql.strip().rstrip(";")
        return sql_clean

    # Registrar en la tabla historial_chat
    def register_chat_history(pregunta, sql_generado, estado):
        try:
            client.table("historial_chat").insert({
                "pregunta": pregunta,
                "sql_generado": sql_generado,
                "estado": estado
            }).execute()
        except Exception:
            pass

    # 5. Historial de Chat interactivo (st.session_state.messages)
    if "messages" not in st.session_state:
        st.session_state.messages = []

    # Mostrar conversación previa
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])
            if "sql" in msg:
                with st.expander("Ver consulta SQL generada"):
                    st.code(msg["sql"], language="sql")
            if "df_result" in msg and msg["df_result"] is not None:
                st.dataframe(msg["df_result"], use_container_width=True)

    # Entrada de Chat
    if prompt := st.chat_input("Escribe tu pregunta sobre las ventas..."):
        with st.chat_message("user"):
            st.markdown(prompt)
        st.session_state.messages.append({"role": "user", "content": prompt})

        with st.chat_message("assistant"):
            metadata_str = get_schema_metadata()

            try:
                # Flujo: Pregunta -> Text-to-SQL Real
                with st.spinner("Copiloto IA pensando y generando SQL..."):
                    sql_clean = generate_text_to_sql(prompt, metadata_str)

                explanation = f"Consulta SQL generada para responder a: '{prompt}'"

                st.write(explanation)

                with st.expander("Ver consulta SQL generada"):
                    st.code(sql_clean, language="sql")

                # Flujo de ejecución Text-to-SQL y conversión de respuesta de Supabase RPC run_sql a DataFrame de Pandas
                with st.spinner("Ejecutando consulta en PostgreSQL..."):
                    try:
                        # Limpiar el query para evitar errores de sintaxis en subconsultas
                        sql_to_run = sql_clean.strip().rstrip(";")

                        # Ejecutar la función RPC en Supabase
                        response = client.rpc("run_sql", {"query": sql_to_run}).execute()
                        data = response.data

                        # Si data viene como string (JSON en texto), lo parseamos
                        if isinstance(data, str):
                            import json
                            data = json.loads(data)

                        # Validar si hubo un error retornado por la función SQL
                        if isinstance(data, dict) and "error" in data:
                            st.error(f"Error en la consulta SQL: {data['error']}")
                            register_chat_history(prompt, sql_to_run, f"Error SQL: {data['error']}")
                            st.session_state.messages.append({
                                "role": "assistant",
                                "content": f"❌ Error en la consulta SQL: {data['error']}",
                                "sql": sql_to_run
                            })
                        else:
                            # Si data es un diccionario único (p. ej. escalar o registro único), lo envolvemos en una lista
                            if isinstance(data, dict):
                                data = [data]

                            if data:
                                df_result = pd.DataFrame(data)
                                st.dataframe(df_result, use_container_width=True)
                                register_chat_history(prompt, sql_to_run, "Exitoso")
                                st.session_state.messages.append({
                                    "role": "assistant",
                                    "content": explanation,
                                    "sql": sql_to_run,
                                    "df_result": df_result
                                })
                            else:
                                st.info("La consulta no devolvió resultados.")
                                register_chat_history(prompt, sql_to_run, "Sin resultados")
                                st.session_state.messages.append({
                                    "role": "assistant",
                                    "content": "*La consulta no devolvió resultados.*",
                                    "sql": sql_to_run
                                })
                    except Exception as e:
                        st.error(f"Error al ejecutar la consulta SQL: {e}")
                        register_chat_history(prompt, sql_clean, f"Error de Conexión: {e}")
                        st.session_state.messages.append({
                            "role": "assistant",
                            "content": f"Lo siento, ocurrió un problema al ejecutar la consulta SQL: {e}",
                            "sql": sql_clean
                        })
            except Exception as e:
                st.error(f"❌ **Error durante la generación**: {e}")
                register_chat_history(prompt, "", f"Generación Fallida: {e}")
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": f"Lo siento, ocurrió un problema al procesar tu solicitud: {e}"
                })


# ==================== PESTAÑA 3: SIMULACIONES WHAT-IF ====================
with tab_whatif:
    st.header("🔮 Simulaciones de Escenarios What-If & Monte Carlo")

    # Organizar en sub-secciones
    subtab_proyecciones, subtab_montecarlo = st.tabs([
        "📈 Proyecciones de Negocio Simples",
        "🎲 Simulación de Monte Carlo"
    ])

    with subtab_proyecciones:
        st.subheader("Simulación de Escenarios Deterministas")
        st.write("Ajusta las variables de negocio para proyectar de manera instantánea el impacto en las ventas totales:")

        # Sliders Interactivos
        incremento_precio = st.slider("Incremento en Precio Unitario (%)", -20.0, 50.0, 0.0, 1.0, key="wi_precio")
        incremento_volumen = st.slider("Incremento en Volumen de Transacciones (%)", -20.0, 100.0, 0.0, 1.0, key="wi_volumen")
        descuento_promedio = st.slider("Descuento Promedio Aplicado (%)", 0.0, 50.0, 5.0, 0.5, key="wi_descuento")

        # Calcular Proyecciones
        current_sales = df_sales['ventas'].sum() if not df_sales.empty else 0.0
        factor_precio = 1 + (incremento_precio / 100.0)
        factor_volumen = 1 + (incremento_volumen / 100.0)
        factor_descuento = 1 - (descuento_promedio / 100.0)

        projected_sales = current_sales * factor_precio * factor_volumen * (factor_descuento / 0.95)

        st.markdown("### Proyección de Resultados de Negocio")
        col_cur, col_proj, col_diff = st.columns(3)
        with col_cur:
            st.metric("Ventas Actuales", format_currency_short(current_sales))
        with col_proj:
            st.metric("Ventas Proyectadas", format_currency_short(projected_sales))
        with col_diff:
            cambio = projected_sales - current_sales
            st.metric(
                "Variación Estimada",
                format_currency_short(cambio),
                delta=f"{((projected_sales - current_sales) / current_sales * 100):+.1f}%" if current_sales > 0 else "0.0%"
            )

    with subtab_montecarlo:
        st.subheader("🎲 Simulación de Monte Carlo & Análisis Decisional")
        st.write("Simula miles de escenarios de ventas posibles utilizando un modelo probabilístico normal (Campana de Gauss) para analizar riesgos y viabilidad.")

        # 1. Obtención de parámetros históricos (media y desviación estándar)
        sales_data = filtered_sales['ventas'] if not filtered_sales.empty else df_sales['ventas']

        # Calcular media y desviación estándar de transacciones individuales
        media_historica = float(sales_data.mean()) if len(sales_data) > 0 else 1000.0
        desviacion_historica = float(sales_data.std()) if len(sales_data) > 1 else 200.0

        # Ofrecer controles interactivos al usuario
        col_ctrl1, col_ctrl2 = st.columns(2)
        with col_ctrl1:
            n_simulaciones = st.radio(
                "Número de Simulaciones",
                options=[1000, 5000, 10000],
                index=1,
                horizontal=True,
                help="Número de escenarios aleatorios a generar."
            )
            volatilidad_selected = st.selectbox(
                "Incertidumbre / Volatilidad Esperada",
                options=['10% (Baja)', '15% (Moderada)', '25% (Alta)', '40% (Crítica)'],
                index=1,
                help="Ajusta la incertidumbre de la simulación comercial."
            )
            volatilidad_map = {
                '10% (Baja)': 10.0,
                '15% (Moderada)': 15.0,
                '25% (Alta)': 25.0,
                '40% (Crítica)': 40.0
            }
            volatilidad_pct = volatilidad_map[volatilidad_selected]
        with col_ctrl2:
            meta_ventas = st.number_input(
                "Meta de Ingresos Totales ($)",
                min_value=1.0,
                value=float(round(media_historica * 1.05, 2)),
                step=1000.0,
                help="Meta financiera general que se desea alcanzar o superar."
            )

        # 2. Generación de la Simulación Monte Carlo (Numpy)
        # Asegurar semilla aleatoria reproducible
        np.random.seed(42)
        sigma_simulada = media_historica * (volatilidad_pct / 100.0)
        simulated_values = np.random.normal(loc=media_historica, scale=sigma_simulada, size=n_simulaciones)

        # 3. Métricas Estadísticas del Escenario
        p5_pesimista = np.percentile(simulated_values, 5)
        p95_optimista = np.percentile(simulated_values, 95)
        esperado_media = np.mean(simulated_values)

        prob_superar_meta = (simulated_values > meta_ventas).sum() / n_simulaciones * 100.0

        st.markdown("### Métricas de Escenarios Probabilísticos")
        m_col1, m_col2, m_col3, m_col4 = st.columns(4)
        with m_col1:
            st.metric(
                label="🔴 Escenario Pesimista (P5)",
                value=format_currency_full(p5_pesimista),
                help="Existe solo un 5% de probabilidad de que las ventas estén por debajo de este valor."
            )
        with m_col2:
            st.metric(
                label="🔵 Escenario Esperado (Media)",
                value=format_currency_full(esperado_media),
                help="El promedio matemático de todos los escenarios simulados."
            )
        with m_col3:
            st.metric(
                label="🟢 Escenario Optimista (P95)",
                value=format_currency_full(p95_optimista),
                help="Existe un 95% de probabilidad de que las ventas estén por debajo de este valor (o 5% de que lo superen)."
            )
        with m_col4:
            st.metric(
                label="🎯 Probabilidad de Superar Meta",
                value=f"{prob_superar_meta:.2f}%",
                help=f"Porcentaje de escenarios simulados en los que la venta supera ${meta_ventas:,.2f}"
            )

        # 4. Visualización Gráfica con Curva de Gauss (Plotly)
        import plotly.graph_objects as go

        # Crear histograma
        fig_mc = go.Figure()

        # Histograma con densidad relativa
        fig_mc.add_trace(go.Histogram(
            x=simulated_values,
            histnorm='probability density',
            name='Frecuencia Simulada',
            marker_color='rgba(100, 149, 237, 0.6)',
            nbinsx=50,
            hovertemplate="Rango: %{x}<br>Densidad: %{y:,.5f}<extra></extra>"
        ))

        # Curva de densidad teórica (Campana de Gauss)
        xmin, xmax = float(np.min(simulated_values)), float(np.max(simulated_values))
        x_axis = np.linspace(xmin, xmax, 100)
        # Fórmula de densidad normal
        y_axis = (1 / (sigma_simulada * np.sqrt(2 * np.pi))) * np.exp(-0.5 * ((x_axis - media_historica) / sigma_simulada) ** 2)

        fig_mc.add_trace(go.Scatter(
            x=x_axis,
            y=y_axis,
            mode='lines',
            name='Curva Normal Teórica',
            line=dict(color='orange', width=3),
            hovertemplate="Venta: $%{x:,.2f}<br>Densidad: %{y:,.5f}<extra></extra>"
        ))

        # Líneas verticales para los escenarios clave
        # Pesimista P5
        fig_mc.add_vline(x=p5_pesimista, line_width=2, line_dash="dash", line_color="red",
                         annotation_text="P5 (Pesimista)", annotation_position="top left")
        # Media Esperada
        fig_mc.add_vline(x=esperado_media, line_width=2, line_dash="dash", line_color="blue",
                         annotation_text="Media (Esperado)", annotation_position="top left")
        # Optimista P95
        fig_mc.add_vline(x=p95_optimista, line_width=2, line_dash="dash", line_color="green",
                         annotation_text="P95 (Optimista)", annotation_position="top right")
        # Meta de Ventas
        fig_mc.add_vline(x=meta_ventas, line_width=2.5, line_color="purple",
                         annotation_text="Meta", annotation_position="bottom right")

        fig_mc.update_layout(
            title="Distribución de Ventas Simuladas (Monte Carlo)",
            xaxis_title="Ventas ($)",
            yaxis_title="Densidad de Probabilidad",
            hovermode="closest",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
        )

        st.plotly_chart(fig_mc, use_container_width=True)

        # 5. Resumen de Toma de Decisiones Decisionales
        st.markdown("### 📋 Análisis Decisional de Viabilidad")

        # Evaluación heurística de viabilidad
        if prob_superar_meta >= 70.0:
            st.success(
                f"🟢 **Viabilidad Financiera: ALTA ({prob_superar_meta:.1f}%)**\n\n"
                f"La probabilidad de superar la meta de **${meta_ventas:,.2f}** es muy alta. "
                "Bajo las condiciones actuales de volatilidad y precio, el negocio se encuentra en una zona de confort financiero "
                "donde la mayoría de las transacciones son altamente rentables. Recomendación: Mantener la estrategia comercial e "
                "invertir excedentes en expansión de canales."
            )
        elif prob_superar_meta >= 40.0:
            st.info(
                f"🟡 **Viabilidad Financiera: MODERADA / ESTABLE ({prob_superar_meta:.1f}%)**\n\n"
                f"Existe una probabilidad intermedia de alcanzar o superar la meta de **${meta_ventas:,.2f}**. "
                "El negocio se mantiene balanceado pero expuesto a la volatilidad comercial. "
                "Cualquier incremento en costos operativos o variaciones negativas en el mercado podría comprometer el margen de ganancias. "
                "Recomendación: Implementar campañas promocionales selectivas para impulsar el ticket promedio y mitigar riesgos."
            )
        else:
            st.warning(
                f"🔴 **Viabilidad Financiera: ALTO RIESGO / BAJA ({prob_superar_meta:.1f}%)**\n\n"
                f"La probabilidad de superar la meta de **${meta_ventas:,.2f}** es baja. "
                "El escenario simulado revela que las fluctuaciones normales y la volatilidad actual ponen en riesgo el logro de los objetivos financieros. "
                "Recomendación: Es prioritario revisar la estructura de precios unitarios o reducir la variabilidad del proceso (volatilidad) "
                "mediante controles de calidad o rediseño de canales de venta para evitar pérdidas."
            )
