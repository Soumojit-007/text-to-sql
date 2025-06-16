import streamlit as st
import os
import base64
from io import BytesIO
from datetime import datetime
import google.generativeai as genai
from google.api_core import exceptions as google_exceptions

# Set page config FIRST - before any other Streamlit commands
st.set_page_config(
    page_title="QueryCraft - Text to SQL Converter",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Try to import optional dependencies with fallback
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    st.warning("python-dotenv not installed. Make sure to set GOOGLE_API_KEY environment variable manually.")

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

# Constants
SENSITIVE_KEYWORDS = ['password', 'credit_card', 'ssn', 'social security', 'pin']
MAX_QUERY_LENGTH = 2000

# Initialize session state
if 'query_history' not in st.session_state:
    st.session_state.query_history = []

@st.cache_resource
def initialize_gemini():
    """Initialize Gemini AI model with error handling using current model names"""
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        st.error("❌ GOOGLE_API_KEY not found in environment variables. Please set your API key.")
        st.info("💡 Create a .env file with: GOOGLE_API_KEY=AIzaSyBAD3imd-Y6hZfOz-wPdWuTkiddsIikudY")
        return None
    
    try:
        genai.configure(api_key=api_key)
        
        # Try current available models in order of preference
        model_names = [
            'gemini-2.0-flash-exp',  # Latest experimental model
            'gemini-1.5-flash-002',  # Updated stable model
            'gemini-1.5-flash-latest',  # Latest alias
            'gemini-1.5-flash',  # Fallback
            'gemini-1.5-pro-002',  # Pro model
            'gemini-1.5-pro-latest',  # Pro latest
            'gemini-1.5-pro'  # Pro fallback
        ]
        
        for model_name in model_names:
            try:
                model = genai.GenerativeModel(model_name)
                # Test the model with a simple prompt
                test_response = model.generate_content("Hello")
                st.success(f"✅ Successfully connected to {model_name}")
                return model
            except google_exceptions.NotFound:
                continue
            except google_exceptions.PermissionDenied as e:
                st.error(f"❌ Permission denied for {model_name}: {str(e)}")
                continue
            except Exception as e:
                st.warning(f"⚠️ Error with {model_name}: {str(e)}")
                continue
        
        # If no model works, show error
        st.error("❌ No available Gemini models found. Please check your API key and try again.")
        st.info("💡 Note: Some models may not be available in your region or require prior usage.")
        return None
        
    except Exception as e:
        st.error(f"❌ Error initializing Gemini AI: {str(e)}")
        return None

def validate_sql(query):
    """Basic SQL validation"""
    if not query:
        return False, "Empty query"
        
    query = query.lower().strip()
    if not query.startswith(('select', 'insert', 'update', 'delete')):
        return False, "Query must start with SELECT, INSERT, UPDATE, or DELETE"
    if ';' in query[:-1]:  # Allow only at end
        return False, "Multiple queries not allowed"
    if any(keyword in query for keyword in ['drop', 'truncate', 'alter']):
        return False, "Potentially dangerous operation detected"
    return True, ""

def clean_sql_query(sql_query):
    """Clean and format SQL query response"""
    if not sql_query:
        return ""
        
    # Remove markdown code blocks
    if sql_query.startswith("```sql"):
        sql_query = sql_query[6:]
    elif sql_query.startswith("```"):
        sql_query = sql_query[3:]
    
    if sql_query.endswith("```"):
        sql_query = sql_query[:-3]
    
    # Remove common prefixes
    prefixes_to_remove = ["SQL Query:", "SQL:", "Query:", "Answer:"]
    for prefix in prefixes_to_remove:
        if sql_query.strip().startswith(prefix):
            sql_query = sql_query.strip()[len(prefix):].strip()
    
    return sql_query.strip()

def get_gemini_response(input_text, model):
    """Get response from Gemini AI model with enhanced error handling"""
    if not model:
        return "Error: Gemini AI model not initialized"
    
    # Check for sensitive keywords
    if any(keyword in input_text.lower() for keyword in SENSITIVE_KEYWORDS):
        return "Error: Query contains potentially sensitive keywords"
    
    # Check length
    if len(input_text) > MAX_QUERY_LENGTH:
        return f"Error: Query too long (max {MAX_QUERY_LENGTH} characters)"
    
    prompt = f"""
    You are an expert in converting English questions to SQL query!
    The SQL database has the following tables and columns:
    
    **Database Schema:**
    1. **employees** table: employee_id (PK), first_name, last_name, email, phone, hire_date, job_id (FK), salary, department_id (FK)
    2. **departments** table: department_id (PK), department_name, manager_id (FK), location_id (FK)
    3. **jobs** table: job_id (PK), job_title, min_salary, max_salary
    4. **locations** table: location_id (PK), street_address, postal_code, city, state_province, country_id
    5. **customers** table: customer_id (PK), first_name, last_name, email, phone, address, city, state, country
    6. **orders** table: order_id (PK), customer_id (FK), order_date, total_amount, status
    7. **products** table: product_id (PK), product_name, category, price, stock_quantity
    8. **order_items** table: order_item_id (PK), order_id (FK), product_id (FK), quantity, unit_price
    
    **Instructions:**
    - Convert the following English question to a proper SQL query
    - Use appropriate JOINs when querying multiple tables
    - Include proper WHERE clauses for filtering
    - Use ORDER BY and LIMIT when appropriate
    - Ensure the query is syntactically correct
    - Return ONLY the SQL query without explanations
    - Never include DROP, TRUNCATE, or other destructive operations
    
    **Question:** {input_text}
    
    **SQL Query:**
    """
    
    try:
        response = model.generate_content(prompt)
        cleaned_query = clean_sql_query(response.text)
        is_valid, validation_msg = validate_sql(cleaned_query)
        if not is_valid:
            return f"Validation Error: {validation_msg}"
        return cleaned_query
    except ValueError as e:
        # Handle content policy violations
        if "policy" in str(e).lower() or "safety" in str(e).lower():
            return "Error: Prompt blocked for safety reasons"
        return f"Error: {str(e)}"
    except google_exceptions.InvalidArgument as e:
        return f"Error: Invalid prompt - {str(e)}"
    except google_exceptions.PermissionDenied as e:
        return f"Error: API key rejected - {str(e)}"
    except google_exceptions.ResourceExhausted as e:
        return f"Error: API quota exceeded - {str(e)}"
    except Exception as e:
        return f"Error generating SQL query: {str(e)}"

def create_background_gradient():
    """Create a CSS background gradient instead of using image file"""
    return """
    <style>
    .stApp {
        background: linear-gradient(135deg, #1e1e2e 0%, #2d2d44 50%, #3a3a52 100%);
        background-attachment: fixed;
    }
    </style>
    """

# Enhanced Custom CSS with better visibility, contrast, and BLACK navigation text
st.markdown("""
<style>
    .stApp {
        background: linear-gradient(135deg, #1e1e2e 0%, #2d2d44 100%);
        color: #ffffff;
    }
    
    /* FIXED: Navigation text to BLACK */
    .stSelectbox label {
        color: #000000 !important;
        font-weight: 600 !important;
        font-size: 1.1rem !important;
    }
    
    .stSelectbox > div > div {
        background-color: #ffffff !important;
        color: #000000 !important;
        border: 2px solid #4CAF50 !important;
    }
    
    .stSelectbox option {
        color: #000000 !important;
        background-color: #ffffff !important;
    }
    
    /* Sidebar styling with black text for navigation */
    .css-1d391kg {
        background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%) !important;
    }
    
    .css-1d391kg .stSelectbox label {
        color: #000000 !important;
        font-weight: 700 !important;
    }
    
    .css-1d391kg .stMarkdown {
        color: #000000 !important;
    }
    
    .css-1d391kg h3 {
        color: #000000 !important;
        font-weight: 700 !important;
    }
    
    .css-1d391kg p, .css-1d391kg li {
        color: #333333 !important;
    }
    
    /* Override Streamlit's default colors for better visibility */
    .stApp > div {
        color: #ffffff !important;
    }
    
    /* Text areas and inputs */
    .stTextArea textarea {
        background-color: #3a3a52 !important;
        color: #ffffff !important;
        border: 2px solid #4CAF50 !important;
        border-radius: 8px !important;
    }
    
    .stTextArea textarea::placeholder {
        color: #b0b0c0 !important;
    }
    
    /* Buttons */
    .stButton > button {
        background: linear-gradient(135deg, #4CAF50, #45a049) !important;
        color: white !important;
        font-weight: 600 !important;
        border: none !important;
        border-radius: 8px !important;
        padding: 0.5rem 1rem !important;
    }
    
    .stButton > button:hover {
        background: linear-gradient(135deg, #45a049, #3d8b40) !important;
        transform: translateY(-2px) !important;
    }
    
    .main-header {
        font-size: 3.5rem;
        font-weight: 700;
        color: #ffffff;
        text-align: center;
        margin-bottom: 2rem;
        text-shadow: 2px 2px 4px rgba(0,0,0,0.8);
        background: linear-gradient(135deg, #4CAF50, #66BB6A);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
    }
    
    .sub-header {
        font-size: 2rem;
        font-weight: 600;
        color: #66BB6A;
        margin-bottom: 1rem;
        text-shadow: 1px 1px 2px rgba(0,0,0,0.5);
    }
    
    .description {
        font-size: 1.1rem;
        color: #f0f0f0;
        margin-bottom: 2rem;
        line-height: 1.6;
        text-align: justify;
    }
    
    .highlight-box {
        background: linear-gradient(135deg, #4CAF50 0%, #66BB6A 100%);
        color: white;
        padding: 1.5rem;
        border-radius: 12px;
        text-align: center;
        font-size: 1.3rem;
        font-weight: 600;
        margin: 2rem 0;
        box-shadow: 0 4px 15px rgba(76, 175, 80, 0.3);
    }
    
    .feature-card {
        background: linear-gradient(135deg, #3a3a52 0%, #4a4a62 100%);
        color: #ffffff;
        padding: 1.5rem;
        border-radius: 12px;
        margin: 1rem 0;
        border-left: 4px solid #4CAF50;
        box-shadow: 0 4px 15px rgba(0,0,0,0.2);
        transition: transform 0.3s ease, box-shadow 0.3s ease;
    }
    
    .feature-card:hover {
        transform: translateY(-3px);
        box-shadow: 0 8px 25px rgba(76, 175, 80, 0.3);
    }
    
    .feature-title {
        font-size: 1.2rem;
        font-weight: 700;
        color: #66BB6A;
        margin-bottom: 0.5rem;
    }
    
    .feature-desc {
        color: #e0e0e0;
        line-height: 1.5;
    }
    
    .history-item {
        background: linear-gradient(135deg, #3a3a52 0%, #4a4a62 100%);
        color: #ffffff;
        padding: 1.5rem;
        border-radius: 10px;
        margin: 1rem 0;
        border-left: 4px solid #4CAF50;
        box-shadow: 0 2px 10px rgba(0,0,0,0.2);
    }
    
    .history-question {
        font-weight: 700;
        color: #66BB6A;
        margin-bottom: 0.5rem;
        font-size: 1.1rem;
    }
    
    .history-query {
        background: #2a2a3e;
        padding: 1rem;
        border-radius: 6px;
        font-family: 'Courier New', monospace;
        color: #ffffff;
        margin: 0.5rem 0;
        border: 1px solid #4CAF50;
    }
    
    .error-box {
        background: linear-gradient(135deg, #f44336 0%, #d32f2f 100%);
        color: white;
        padding: 1.2rem;
        border-radius: 10px;
        margin: 1rem 0;
        font-weight: 600;
        box-shadow: 0 4px 15px rgba(244, 67, 54, 0.3);
    }
    
    .success-box {
        background: linear-gradient(135deg, #4CAF50 0%, #66BB6A 100%);
        color: white;
        padding: 1.2rem;
        border-radius: 10px;
        margin: 1rem 0;
        font-weight: 600;
        box-shadow: 0 4px 15px rgba(76, 175, 80, 0.3);
    }
    
    /* FIXED: Code blocks with stable visibility - SQL query MUST be visible */
    .stCode {
        background: #f8f9fa !important;
        border: 2px solid #4CAF50 !important;
        border-radius: 8px !important;
        padding: 1rem !important;
        position: relative !important;
        opacity: 1 !important;
        visibility: visible !important;
        transition: none !important;
        display: block !important;
    }
    
    .stCode:hover {
        background: #f8f9fa !important;
        opacity: 1 !important;
        visibility: visible !important;
    }
    
    .stCode code {
        color: #212529 !important;
        background: transparent !important;
        font-family: 'Courier New', Consolas, monospace !important;
        font-size: 14px !important;
        font-weight: 500 !important;
        opacity: 1 !important;
        visibility: visible !important;
        display: block !important;
        white-space: pre-wrap !important;
    }
    
    .stCode code:hover {
        opacity: 1 !important;
        visibility: visible !important;
    }
    
    .stCode pre {
        background: transparent !important;
        color: #212529 !important;
        margin: 0 !important;
        padding: 0 !important;
        opacity: 1 !important;
        visibility: visible !important;
        display: block !important;
    }
    
    /* Ensure all code elements are visible */
    .stCode * {
        color: #212529 !important;
        opacity: 1 !important;
        visibility: visible !important;
    }
    
    /* Expander */
    .streamlit-expanderHeader {
        background: linear-gradient(135deg, #3a3a52 0%, #4a4a62 100%) !important;
        color: #ffffff !important;
        font-weight: 600 !important;
    }
    
    .streamlit-expanderContent {
        background: #2a2a3e !important;
        color: #ffffff !important;
    }
    
    /* Info boxes */
    .stInfo {
        background: linear-gradient(135deg, #2196F3 0%, #1976D2 100%) !important;
        color: white !important;
    }
    
    .stSuccess {
        background: linear-gradient(135deg, #4CAF50 0%, #66BB6A 100%) !important;
        color: white !important;
    }
    
    .stError {
        background: linear-gradient(135deg, #f44336 0%, #d32f2f 100%) !important;
        color: white !important;
    }
    
    .stWarning {
        background: linear-gradient(135deg, #FF9800 0%, #F57C00 100%) !important;
        color: white !important;
    }
    
    @media screen and (max-width: 768px) {
        .main-header { font-size: 2.5rem; }
        .sub-header { font-size: 1.8rem; }
        .feature-card { padding: 1rem; }
    }
</style>
""", unsafe_allow_html=True)

def home_page():
    """Home page content"""
    st.markdown("""
    <div class="highlight-box">
        🚀 Making Database Queries as Easy as Conversation!
    </div>
    """, unsafe_allow_html=True)
    
    st.markdown("""
    <div class="description">
    Welcome to <strong>QueryCraft</strong>, your revolutionary solution for simplifying database interactions through natural 
    language queries. Powered by Google's cutting-edge Gemini AI, QueryCraft seamlessly converts 
    everyday language into accurate SQL queries, eliminating the need for SQL expertise. 
    </div>
    """, unsafe_allow_html=True)
    
    # Quick start section
    st.markdown('<h2 class="sub-header">🚀 Quick Start Guide</h2>', unsafe_allow_html=True)
    
    cols = st.columns(3)
    features = [
        ("💬 Type Your Question", "Simply describe what data you need in plain English"),
        ("⚡ Get SQL Query", "Our AI instantly converts your question to optimized SQL"),
        ("🎯 Execute & Analyze", "Copy the query to your database and get results")
    ]
    
    for col, (title, desc) in zip(cols, features):
        with col:
            st.markdown(f"""
            <div class="feature-card">
                <div class="feature-title">{title}</div>
                <div class="feature-desc">{desc}</div>
            </div>
            """, unsafe_allow_html=True)

def query_converter_page():
    """Query converter page with enhanced functionality"""
    st.markdown('<h2 class="sub-header">🔄 Start Your Query Conversion</h2>', unsafe_allow_html=True)
    
    if 'model' not in st.session_state or not st.session_state.model:
        st.error("🚫 Cannot convert queries without Gemini AI connection. Please check your API key setup.")
        if st.button("🔄 Retry Connection"):
            st.session_state.model = initialize_gemini()
            st.rerun()
        return
    
    # Example queries
    with st.expander("💡 Example Questions"):
        st.markdown("""
        - "Show me all employees in the Sales department"
        - "Who are the top 5 highest paid employees?"
        - "List customers with pending orders"
        - "Find orders over $1000 from last month"
        - "Show products with low stock (less than 10 items)"
        """)
    
    # Input section
    input_text = st.text_area(
        "Describe what data you need:",
        placeholder="Example: Show employees hired in the last 6 months",
        height=120,
        key="query_input"
    )
    
    # Options
    col1, col2 = st.columns([1, 4])
    with col1:
        submit = st.button("🚀 Convert to SQL", type="primary", key="convert_btn")
    with col2:
        save_history = st.checkbox("💾 Save to history", value=True, key="save_history")
    
    # Process query
    if submit and input_text.strip():
        with st.spinner("🔄 Converting to SQL..."):
            sql_query = get_gemini_response(input_text, st.session_state.model)
            
            if sql_query.startswith("Error"):
                st.markdown(f"""
                <div class="error-box">
                    ❌ {sql_query}
                </div>
                """, unsafe_allow_html=True)
                return
            
            st.markdown('<h3 class="sub-header">✅ Generated SQL Query:</h3>', unsafe_allow_html=True)
            
            # Display the SQL query without copy button
            if sql_query and sql_query.strip():
                st.code(sql_query, language="sql")
            else:
                st.error("❌ No SQL query was generated. Please try again.")
            
            # Save to history
            if save_history and sql_query and not sql_query.startswith("Error"):
                st.session_state.query_history.append({
                    "question": input_text,
                    "sql_query": sql_query,
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M")
                })
                st.success("💾 Saved to history!")

def history_page():
    """Query history page"""
    st.markdown('<h2 class="sub-header">📚 Query History</h2>', unsafe_allow_html=True)
    
    if not st.session_state.query_history:
        st.info("🔍 No query history yet")
        if st.button("🔄 Go to Query Converter"):
            st.session_state.current_page = "🔄 Query Converter"
            st.rerun()
        return
    
    # Clear history button
    if st.button("🗑️ Clear History", type="secondary"):
        st.session_state.query_history = []
        st.success("✅ History cleared!")
        st.rerun()
    
    # Display history
    for idx, item in enumerate(reversed(st.session_state.query_history)):
        with st.expander(f"Query {idx+1}: {item['question'][:50]}..."):
            st.markdown(f"""
            <div class="history-item">
                <div class="history-question">Question:</div>
                <p>{item['question']}</p>
                <div class="history-question">SQL Query:</div>
                <div class="history-query">{item['sql_query']}</div>
                <small>Saved at: {item['timestamp']}</small>
            </div>
            """, unsafe_allow_html=True)
            
            cols = st.columns([1, 1])
            with cols[0]:
                if st.button(f"📋 Copy Query {idx+1}", key=f"copy_history_{idx}"):
                    st.text_area(
                        f"Select all and copy (Ctrl+A, Ctrl+C):",
                        value=item['sql_query'],
                        height=80,
                        key=f"copy_area_history_{idx}",
                        help="Click in the box, select all (Ctrl+A), then copy (Ctrl+C)"
                    )
                    st.success("✅ Query ready to copy!")
            with cols[1]:
                if st.button(f"↻ Regenerate {idx+1}", key=f"regen_{idx}"):
                    st.session_state.query_input = item['question']
                    st.session_state.current_page = "🔄 Query Converter"
                    st.rerun()

def main():
    """Main application function"""
    # Initialize model if not already done
    if 'model' not in st.session_state:
        st.session_state.model = initialize_gemini()
    
    # Apply background gradient instead of image
    st.markdown(create_background_gradient(), unsafe_allow_html=True)
    
    # Header
    st.markdown('<h1 class="main-header">🔍 QueryCraft</h1>', unsafe_allow_html=True)
    
    # Navigation
    page = st.sidebar.selectbox(
        "Navigate", 
        ["🏠 Home", "🔄 Query Converter", "📚 History"],
        key="current_page"
    )
    
    # Display API status in sidebar
    with st.sidebar:
        st.markdown("---")
        if st.session_state.get('model'):
            st.markdown("""
            <div class="success-box">
                ✅ Gemini AI Connected
            </div>
            """, unsafe_allow_html=True)
        else:
            st.markdown("""
            <div class="error-box">
                ❌ Gemini AI Not Connected
            </div>
            """, unsafe_allow_html=True)
        
        st.markdown("---")
        st.markdown("### 📊 Database Schema")
        st.markdown("""
        - **employees** (employee_id, name, email, etc.)
        - **departments** (department_id, name, etc.)
        - **customers** (customer_id, name, email, etc.)
        - **orders** (order_id, customer_id, date, etc.)
        - **products** (product_id, name, price, etc.)
        - **order_items** (order_id, product_id, quantity)
        """)
        
        st.markdown("---")
        if st.button("🔄 Refresh Connection"):
            st.session_state.model = initialize_gemini()
            st.rerun()
    
    # Route to different pages
    if page == "🏠 Home":
        home_page()
    elif page == "🔄 Query Converter":
        query_converter_page()
    elif page == "📚 History":
        history_page()

if __name__ == "__main__":
    # Create .env file if it doesn't exist
    if not os.path.exists('.env'):
        with open('.env', 'w') as f:
            f.write('# Add your Google API key here\n')
            f.write('GOOGLE_API_KEY=AIzaSyBAD3imd-Y6hZfOz-wPdWuTkiddsIikudY\n')
    
    main()