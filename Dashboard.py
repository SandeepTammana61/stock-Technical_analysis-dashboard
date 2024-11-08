import streamlit as st
import yfinance as yf
import plotly.express as px
import pandas as pd
import numpy as np
from datetime import date, timedelta
import openai
from stocknews import StockNews
import subprocess
import time
import threading
import queue
import platform

# Streamlit Page Configuration
st.set_page_config(
    page_title="Stock Analysis Dashboard",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for UI styling
st.markdown("""
    <style>
    .stAlert {
        padding: 1rem;
        margin: 1rem 0;
    }
    .metric-card {
        background-color: #f8f9fa;
        padding: 1rem;
        border-radius: 0.5rem;
        box-shadow: 0 1px 3px rgba(0,0,0,0.12);
    }
    </style>
""", unsafe_allow_html=True)

st.title('📈 Stock Analysis Dashboard ')   

# Cache stock data fetching
@st.cache_data(ttl=3600)  # Cache for 1 hour
def get_stock_data(ticker_symbol):
    try:
        stock = yf.Ticker(ticker_symbol)
        hist = stock.history(period="1y")
        info = stock.info
        return hist, info, None
    except Exception as e:
        return None, None, str(e)

# Ollama response function with queue handling for timeout
def ollama_response_with_queue(prompt, model="phi3:mini", timeout=30):
    def target_function(q):
        try:
            startupinfo = None
            creation_flags = 0
            if platform.system() == 'Windows':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE
                creation_flags = subprocess.CREATE_NO_WINDOW
            command = ["ollama", "run", model, prompt]
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                errors='replace',
                startupinfo=startupinfo,
                creationflags=creation_flags
            )
            stdout, stderr = process.communicate()
            stdout = '\n'.join([line for line in stdout.split('\n') 
                                if "failed to get console mode" not in line])
            if process.returncode == 0:
                q.put(('success', stdout.strip()))
            else:
                filtered_stderr = '\n'.join([line for line in stderr.split('\n') 
                                             if "failed to get console mode" not in line])
                q.put(('error', f"Command error: {filtered_stderr}" if filtered_stderr else stderr))
        except Exception as e:
            q.put(('error', f"Exception: {str(e)}"))

    result_queue = queue.Queue()
    thread = threading.Thread(target=target_function, args=(result_queue,))
    thread.daemon = True
    thread.start()
    try:
        status, result = result_queue.get(timeout=timeout)
        return result if status == 'success' else f"Error: {result}"
    except queue.Empty:
        return "Error: Request timed out. Please try again or adjust the timeout setting."

# Sidebar Configuration
with st.sidebar:
    st.header("📊 Configuration")
    ticker = st.text_input('Stock Ticker', value='TSLA', placeholder='Enter stock ticker symbol', help="Enter the stock symbol (e.g., AAPL for Apple Inc.)").upper()
    start_date = st.sidebar.date_input('Start Date', value=date(2023, 9, 13))
    end_date = st.sidebar.date_input('End Date')
    analyze_button = st.button('🔄 Analyze Stock', use_container_width=True)
    model = st.selectbox('AI Model', ['phi3:mini', 'llama2', 'mistral'], help="Select the AI model for analysis")
    timeout = st.slider('Response Timeout (seconds)', min_value=10, max_value=120, value=45, help="Adjust if you're experiencing timeout issues")
    
 


    
# Download data using yfinance
data = yf.download(ticker, start=start_date, end=end_date)

# Plot the adjustable and freely interactive plot
fig = px.line(data, x=data.index, y='Adj Close', title=f"{ticker} Stock Price Movement")
fig.update_layout(
    title=f"{ticker} Stock Price Movement",
    xaxis_title="Date",
    yaxis_title="Adjusted Close Price",
    hovermode="x",  # Hover effects on x-axis
    dragmode="pan"  # Enable panning by default for mouse dragging
)
fig.update_xaxes(rangeslider_visible=True)  # Add a range slider for fine control
fig.update_yaxes(fixedrange=False)  # Allow free zooming in the y-axis

# Display the chart in Streamlit with container width to fill available space
st.plotly_chart(fig, use_container_width=True)

if analyze_button:
    with st.spinner('Fetching stock data...'):
        hist_data, stock_info, error = get_stock_data(ticker)
        if error:
            st.error(f"Failed to fetch stock data: {error}")
        else:
            st.session_state.current_ticker = ticker
            st.session_state.hist_data = hist_data
            st.session_state.stock_info = stock_info
            col1, col2, col3, col4 = st.columns(4)
            metrics = {
                "Current Price": stock_info.get('currentPrice'),
                "Market Cap": stock_info.get('marketCap'),
                "P/E Ratio": stock_info.get('trailingPE'),
                "52W High": stock_info.get('fiftyTwoWeekHigh')
            }
            for col, (label, value) in zip([col1, col2, col3, col4], metrics.items()):
                with col:
                    st.metric(label, value if value else 'N/A')

            # Tabs for different sections
pricing_data, fundamental_data, news, ai_analysis,financial_metrics= st.tabs(['Pricing Data', 'Fundamental Data', 'Top 10 News', 'AI Analysis','financial_metrics'])

# Pricing Data Tab
with pricing_data:
    st.header('Price Movements')
    data2 = hist_data
    data2['% Change'] = data2['Close'].pct_change()
    data2.dropna(inplace=True)
    st.write(data2)
    
    # Calculating Annual Return and Standard Deviation
    annual_return = data2['% Change'].mean() * 252 * 100
    st.write('Annual Returns:', annual_return, '%')
    stdev = data2['% Change'].std() * np.sqrt(252) * 100
    st.write('Standard Deviation:', stdev, '%')
    
    # Calculating and Displaying Sharpe Ratio
    st.write('Sharpe Ratio:', annual_return / stdev)
    
    
# Fundamental Data Tab
with fundamental_data:
    st.subheader('Balance Sheet')
    stock = yf.Ticker(ticker)
    try:
        # Display Balance Sheet
        balance_sheet = stock.balance_sheet
        st.write(balance_sheet)

        # Display Income Statement
        st.subheader('Income Statement')
        income_statement = stock.financials
        st.write(income_statement)

        # Display Cash Flow Statement
        st.subheader('Cash Flow')
        cash_flow = stock.cashflow
        st.write(cash_flow)
    except Exception as e:
        st.write(f"Could not retrieve fundamental data: {e}")

# News Tab
with news:
    st.header(f'News of {ticker}')
    sn = StockNews(ticker, save_news=False)
    df_news = sn.read_rss()
    for i in range(10):
        if i < len(df_news):
            st.subheader(f'News {i + 1}')
            st.write(df_news['published'][i])
            st.write(df_news['title'][i])
            st.write(df_news['summary'][i])
            st.write(f"Title Sentiment: {df_news['sentiment_title'][i]}")
            st.write(f"News Sentiment: {df_news['sentiment_summary'][i]}")

# Financial Metrics Tab
with financial_metrics:
    st.subheader(f'Key Financial Metrics for {ticker}')
    if 'stock_info' in st.session_state:
        info = st.session_state['stock_info']
        metrics = {
            'Revenue Growth': info.get('revenueGrowth', 'N/A'),
            'Profit Margins': info.get('profitMargins', 'N/A'),
            'Operating Margins': info.get('operatingMargins', 'N/A'),
            'Return on Equity': info.get('returnOnEquity', 'N/A'),
            'Debt to Equity': info.get('debtToEquity', 'N/A'),
            'Current Ratio': info.get('currentRatio', 'N/A'),
            'Quick Ratio': info.get('quickRatio', 'N/A'),
            'Beta': info.get('beta', 'N/A')
        }

        # Display metrics in a clean format
        for metric, value in metrics.items():
            if isinstance(value, float):
                st.metric(
                    metric, 
                    f"{value:.2%}" if metric in ['Revenue Growth', 'Profit Margins', 'Operating Margins', 'Return on Equity'] else f"{value:.2f}"
                )
            else:
                st.metric(metric, value)
    else:
        st.info("Click 'Analyze Stock' to view financial metrics")

import random

# AI Analysis Tab with Multiple Randomized Default Fallback Responses
with ai_analysis:
    buy_reason, sell_reason, swot_analysis = st.tabs(['3 Reasons to Buy', '3 Reasons to Sell', 'SWOT Analysis'])
    
    # Multiple default responses for each type of analysis
    default_responses = {
        'buy': [
            """
            1. The stock has demonstrated strong revenue growth and consistent profitability.
            2. The company holds a competitive position in its industry, with a solid market share.
            3. Future growth prospects are favorable due to new product lines or market expansions.
            """,
            """
            1. Positive industry trends provide a strong tailwind for the company’s core business.
            2. The stock has a strong history of dividend payments, providing steady income.
            3. Innovative product development gives it an edge over competitors.
            """,
            """
            1. The company has a strong balance sheet with low debt.
            2. High customer satisfaction and loyalty have driven consistent market demand.
            3. Management has a proven track record of navigating challenges effectively.
            """,
            """
            1. The stock has outperformed its peers in terms of earnings growth.
            2. Significant investments in research and development indicate strong future potential.
            3. Strategic partnerships enhance market reach and operational efficiency.
            """,
            """
            1. Favorable economic conditions and government policies boost its growth potential.
            2. Expansion into international markets provides additional revenue streams.
            3. Strong brand recognition creates a competitive moat in the industry.
            """
        ],
        'sell': [
            """
            1. The stock is currently overvalued, with a high price-to-earnings (P/E) ratio compared to industry peers.
            2. Recent financial performance has shown a decline, with lower revenues and profits.
            3. The company faces significant competition or regulatory risks that may impact future performance.
            """,
            """
            1. Macroeconomic headwinds could adversely affect the company’s revenue growth.
            2. Rising operational costs have impacted profit margins, making the stock less attractive.
            3. Key executives have recently left the company, indicating potential instability.
            """,
            """
            1. The company is heavily reliant on a single product or customer, posing a risk.
            2. Declining market demand has resulted in missed revenue targets.
            3. High levels of debt could lead to financial stress in a downturn.
            """,
            """
            1. Competitive pressures have eroded the company’s market share over time.
            2. New regulations are likely to raise compliance costs and reduce profitability.
            3. Technological disruptions in the industry may leave the company at a disadvantage.
            """,
            """
            1. Management has recently made questionable strategic decisions.
            2. Weakening consumer sentiment or spending patterns pose a risk.
            3. Recent earnings misses have caused the stock to underperform.
            """
        ],
        'swot': [
            """
            **Strengths**:
            - Strong brand recognition and market position.
            - High profit margins and efficient operations.
            
            **Weaknesses**:
            - High dependency on a single market or product.
            - Exposure to currency fluctuations or raw material costs.
            
            **Opportunities**:
            - Expansion into emerging markets.
            - Adoption of new technology trends.
            
            **Threats**:
            - Regulatory changes in key markets.
            - Increased competition from new entrants.
            """,
            """
            **Strengths**:
            - Extensive distribution network and strong customer loyalty.
            - Robust financials with consistent cash flow generation.
            
            **Weaknesses**:
            - Aging product lineup with limited recent innovation.
            - High cost structure compared to competitors.
            
            **Opportunities**:
            - Diversification into related markets or services.
            - Strategic partnerships to enhance capabilities.
            
            **Threats**:
            - Economic downturns affecting consumer demand.
            - Increased regulatory scrutiny in major markets.
            """,
            """
            **Strengths**:
            - Market leadership in key product categories.
            - Strong intellectual property and patents portfolio.
            
            **Weaknesses**:
            - Dependency on cyclical demand in a volatile sector.
            - Supply chain constraints affecting operational efficiency.
            
            **Opportunities**:
            - Investments in digital transformation and automation.
            - Positive demographic shifts driving demand.
            
            **Threats**:
            - Competitor advancements in technology.
            - Geopolitical risks impacting trade routes.
            """,
            """
            **Strengths**:
            - High employee retention and skilled workforce.
            - Access to a broad customer base across multiple regions.
            
            **Weaknesses**:
            - High R&D expenses with uncertain payoffs.
            - Limited diversification in revenue streams.
            
            **Opportunities**:
            - Sustainable and eco-friendly product initiatives.
            - Expansion via mergers and acquisitions.
            
            **Threats**:
            - Cybersecurity threats targeting sensitive data.
            - Price wars driven by industry competition.
            """,
            """
            **Strengths**:
            - Strong market momentum with recent growth in share price.
            - Experienced leadership with a clear strategic vision.
            
            **Weaknesses**:
            - Heavy reliance on a specific geographic region for revenue.
            - Increasing costs of raw materials and labor.
            
            **Opportunities**:
            - New product launches in untapped markets.
            - Adoption of AI and automation to streamline processes.
            
            **Threats**:
            - Rising interest rates impacting borrowing costs.
            - Increased tariffs affecting international sales.
            """
        ]
    }

    for tab, analysis_type in zip([buy_reason, sell_reason, swot_analysis], ['buy', 'sell', 'swot']):
        with tab:
            st.subheader(f'{analysis_type.upper()} Analysis for {ticker}')
            prompt = f"Provide {3 if analysis_type != 'swot' else 'a detailed'} reasons to {analysis_type} {ticker} stock."
            try:
                with st.spinner('Generating analysis...'):
                    response = ollama_response_with_queue(prompt, model, timeout)
                    # Use a random default response if Ollama response is an error or empty
                    if response.startswith('Error') or not response.strip():
                        
                        response = random.choice(default_responses[analysis_type])
                    st.write(response)
            except Exception as e:
                # Fallback to a random default response in case of an exception
                st.error(f"Analysis failed: {str(e)}")
                st.warning(f"Displaying a random default {analysis_type} analysis.")
                st.write(random.choice(default_responses[analysis_type]))



# Footer
st.markdown("---")
st.markdown("""
    <div style='text-align: center'>
        <p><small>🚀 AI-Powered Stock Analysis Dashboard | Data provided by Yahoo Finance</small></p>
        <p><small>⚠️ Disclaimer: This tool provides AI-generated analysis for educational purposes only. 
        Always conduct thorough research before making investment decisions.</small></p>
    </div>
""", unsafe_allow_html=True)
