#!/usr/bin/env python3
"""
NYZTrade Premium Client Management System
WhatsApp-Only Version - No Email, No Special Characters

Usage: python nyztrade_whatsapp_only.py

Author: NIYAS - NYZTrade
Version: 1.0.2 - WhatsApp Only
"""

import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, timedelta
import requests
import json
import os
import sys
import argparse
import time
import logging
from typing import List, Dict
import plotly.express as px
import plotly.graph_objects as go

# Configuration defaults
DEFAULT_CONFIG = {
    "whatsapp": {
        "api_url": "",
        "api_key": "",
        "enabled": False
    },
    "notifications": {
        "days_before_expiry": 1,
        "send_time": "09:00",
        "enabled": True
    },
    "business": {
        "name": "NYZTrade",
        "contact_phone": "+91-9999999999",
        "contact_email": "support@nyztrade.com",
        "website": "https://nyztrade.com",
        "address": "Kerala, India"
    },
    "database": {
        "path": "premium_clients.db"
    }
}

class ConfigManager:
    def __init__(self, config_file='config.json'):
        self.config_file = config_file
        self.config = self.load_config()
    
    def load_config(self):
        try:
            with open(self.config_file, 'r') as f:
                config = json.load(f)
                return self._merge_config(DEFAULT_CONFIG, config)
        except FileNotFoundError:
            return DEFAULT_CONFIG.copy()
    
    def _merge_config(self, default, user):
        for key, value in default.items():
            if key not in user:
                user[key] = value
            elif isinstance(value, dict) and isinstance(user[key], dict):
                user[key] = self._merge_config(value, user[key])
        return user
    
    def save_config(self):
        with open(self.config_file, 'w') as f:
            json.dump(self.config, f, indent=2)
    
    def get(self, path, default=None):
        keys = path.split('.')
        value = self.config
        for key in keys:
            if key in value:
                value = value[key]
            else:
                return default
        return value
    
    def set(self, path, value):
        keys = path.split('.')
        config = self.config
        for key in keys[:-1]:
            if key not in config:
                config[key] = {}
            config = config[key]
        config[keys[-1]] = value

class DatabaseManager:
    def __init__(self, db_path='premium_clients.db'):
        self.db_path = db_path
        self.init_database()
    
    def init_database(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS clients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                phone TEXT,
                whatsapp TEXT,
                registration_date DATE DEFAULT CURRENT_DATE,
                status TEXT DEFAULT 'Active',
                notes TEXT
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS services (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                description TEXT,
                price REAL,
                duration_days INTEGER,
                status TEXT DEFAULT 'Active'
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id INTEGER,
                service_id INTEGER,
                start_date DATE,
                end_date DATE,
                amount_paid REAL,
                payment_method TEXT,
                transaction_id TEXT,
                status TEXT DEFAULT 'Active',
                auto_renewal INTEGER DEFAULT 0,
                FOREIGN KEY (client_id) REFERENCES clients (id),
                FOREIGN KEY (service_id) REFERENCES services (id)
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id INTEGER,
                service_name TEXT,
                notification_type TEXT,
                scheduled_date DATE,
                sent_date DATE,
                status TEXT DEFAULT 'Pending',
                message TEXT,
                FOREIGN KEY (client_id) REFERENCES clients (id)
            )
        ''')
        
        cursor.execute("SELECT COUNT(*) FROM services")
        if cursor.fetchone()[0] == 0:
            default_services = [
                ('EQUITY Premium', 'Advanced equity analysis and trading signals with GEX analysis', 5000.0, 30),
                ('OPTION Premium', 'Professional options trading strategies and real-time GEX/DEX analysis', 7000.0, 30),
                ('VALUATION Premium', 'Comprehensive company valuation and fundamental research reports', 4000.0, 30),
                ('COMBO - Equity + Options', 'Combined equity and options premium package with full access', 10000.0, 30),
                ('ANNUAL - All Services', 'Complete annual access to all premium services and tools', 100000.0, 365)
            ]
            cursor.executemany(
                "INSERT INTO services (name, description, price, duration_days) VALUES (?, ?, ?, ?)",
                default_services
            )
        
        conn.commit()
        conn.close()
    
    def get_connection(self):
        return sqlite3.connect(self.db_path)
    
    def get_clients(self):
        conn = self.get_connection()
        df = pd.read_sql_query("SELECT * FROM clients ORDER BY name", conn)
        conn.close()
        return df
    
    def get_services(self):
        conn = self.get_connection()
        df = pd.read_sql_query("SELECT * FROM services WHERE status = 'Active' ORDER BY name", conn)
        conn.close()
        return df
    
    def get_active_subscriptions(self):
        conn = self.get_connection()
        query = '''
            SELECT s.*, c.name as client_name, c.email, c.phone, c.whatsapp,
                   sv.name as service_name, sv.description, sv.price
            FROM subscriptions s
            JOIN clients c ON s.client_id = c.id
            JOIN services sv ON s.service_id = sv.id
            WHERE s.status = 'Active' AND s.end_date >= date('now')
            ORDER BY s.end_date
        '''
        df = pd.read_sql_query(query, conn)
        conn.close()
        return df
    
    def get_expiring_subscriptions(self, days=1):
        conn = self.get_connection()
        query = '''
            SELECT s.*, c.name as client_name, c.email, c.phone, c.whatsapp,
                   sv.name as service_name, sv.description
            FROM subscriptions s
            JOIN clients c ON s.client_id = c.id
            JOIN services sv ON s.service_id = sv.id
            WHERE s.status = 'Active' 
            AND s.end_date = date('now', '+{} days')
        '''.format(days)
        df = pd.read_sql_query(query, conn)
        conn.close()
        return df

class WhatsAppNotificationManager:
    def __init__(self, config_manager, db_manager):
        self.config = config_manager
        self.db = db_manager
        self.setup_logging()
    
    def setup_logging(self):
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('whatsapp_notifications.log'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)
    
    def send_whatsapp_notification(self, phone, message):
        try:
            if not self.config.get('whatsapp.enabled'):
                self.logger.info("WhatsApp notifications disabled")
                return False
                
            headers = {
                'Authorization': f'Bearer {self.config.get("whatsapp.api_key")}',
                'Content-Type': 'application/json'
            }
            data = {
                'phone': phone,
                'message': message
            }
            
            response = requests.post(
                self.config.get('whatsapp.api_url'), 
                headers=headers, 
                json=data,
                timeout=10
            )
            
            if response.status_code == 200:
                self.logger.info(f"WhatsApp sent to {phone}")
                return True
            else:
                self.logger.error(f"WhatsApp failed for {phone}: {response.text}")
                return False
                
        except Exception as e:
            self.logger.error(f"WhatsApp failed for {phone}: {str(e)}")
            return False
    
    def create_whatsapp_message(self, subscription):
        business_name = self.config.get('business.name')
        contact_phone = self.config.get('business.contact_phone')
        
        message = f"""{business_name} Reminder

Hello {subscription['client_name']}!

Your {subscription['service_name']} subscription expires on {subscription['end_date']}.

Don't miss out on:
- Advanced GEX/DEX Analysis
- Professional Trading Signals  
- Malayalam & English Content
- Priority Expert Support
- Continuous Market Education

Contact us to renew:
Phone: {contact_phone}
YouTube: NYZTrade Channel

Thank you for choosing {business_name}!

This is an automated reminder"""
        
        return message
    
    def log_notification(self, client_id, service_name, status, message=""):
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO notifications 
            (client_id, service_name, notification_type, scheduled_date, sent_date, status, message)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            client_id, service_name, 'whatsapp', 
            datetime.now().date(), datetime.now().date(),
            status, message[:500]
        ))
        
        conn.commit()
        conn.close()
    
    def send_expiry_notifications(self):
        if not self.config.get('notifications.enabled'):
            self.logger.info("Notifications are disabled")
            return
        
        days_before = self.config.get('notifications.days_before_expiry')
        expiring_subscriptions = self.db.get_expiring_subscriptions(days_before)
        
        self.logger.info(f"Found {len(expiring_subscriptions)} subscriptions expiring in {days_before} day(s)")
        
        for _, subscription in expiring_subscriptions.iterrows():
            if subscription['whatsapp']:
                client_id = subscription['client_id']
                service_name = subscription['service_name']
                
                whatsapp_message = self.create_whatsapp_message(subscription)
                success = self.send_whatsapp_notification(subscription['whatsapp'], whatsapp_message)
                
                self.log_notification(
                    client_id, service_name,
                    'sent' if success else 'failed'
                )
                
                self.logger.info(f"Processed WhatsApp for {subscription['client_name']} - {service_name}")

def init_streamlit_app():
    st.set_page_config(
        page_title="NYZTrade - Premium Client Manager",
        page_icon="📈",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    
    if 'config_manager' not in st.session_state:
        st.session_state.config_manager = ConfigManager()
    
    if 'db_manager' not in st.session_state:
        st.session_state.db_manager = DatabaseManager(
            st.session_state.config_manager.get('database.path')
        )
    
    if 'notification_manager' not in st.session_state:
        st.session_state.notification_manager = WhatsAppNotificationManager(
            st.session_state.config_manager,
            st.session_state.db_manager
        )

def show_header():
    st.markdown("""
        <style>
        .main-header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            padding: 1.5rem;
            border-radius: 10px;
            color: white;
            text-align: center;
            margin-bottom: 2rem;
        }
        .metric-card {
            background: white;
            padding: 1rem;
            border-radius: 10px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            border-left: 4px solid #667eea;
        }
        </style>
    """, unsafe_allow_html=True)
    
    business_name = st.session_state.config_manager.get('business.name', 'NYZTrade')
    
    st.markdown(f"""
        <div class="main-header">
            <h1>{business_name} Premium Client Manager</h1>
            <p>WhatsApp-Only Version - Comprehensive management for Equity, Options & Valuation services</p>
        </div>
    """, unsafe_allow_html=True)

def show_dashboard():
    st.header("Dashboard Overview")
    
    clients = st.session_state.db_manager.get_clients()
    subscriptions = st.session_state.db_manager.get_active_subscriptions()
    expiring_soon = st.session_state.db_manager.get_expiring_subscriptions(1)
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("Total Clients", len(clients))
    with col2:
        st.metric("Active Subscriptions", len(subscriptions))
    with col3:
        total_revenue = subscriptions['amount_paid'].sum() if len(subscriptions) > 0 else 0
        st.metric("Monthly Revenue", f"Rs {total_revenue:,.0f}")
    with col4:
        st.metric("Expiring Soon", len(expiring_soon))
    
    if len(subscriptions) > 0:
        col1, col2 = st.columns(2)
        
        with col1:
            service_counts = subscriptions['service_name'].value_counts()
            fig_pie = px.pie(values=service_counts.values, names=service_counts.index, 
                            title="Active Subscriptions by Service")
            st.plotly_chart(fig_pie, use_container_width=True)
        
        with col2:
            revenue_by_service = subscriptions.groupby('service_name')['amount_paid'].sum()
            fig_bar = px.bar(x=revenue_by_service.index, y=revenue_by_service.values,
                           title="Revenue by Service")
            st.plotly_chart(fig_bar, use_container_width=True)
    
    if len(expiring_soon) > 0:
        st.subheader("Expiring Tomorrow")
        for _, row in expiring_soon.iterrows():
            st.warning(f"{row['client_name']} - {row['service_name']} expires {row['end_date']}")
        
        if st.button("Send WhatsApp Reminders Now", type="primary"):
            try:
                st.session_state.notification_manager.send_expiry_notifications()
                st.success(f"WhatsApp reminders sent to {len(expiring_soon)} clients!")
            except Exception as e:
                st.error(f"Failed to send notifications: {str(e)}")
    
    st.subheader("Recent Active Subscriptions")
    if len(subscriptions) > 0:
        display_cols = ['client_name', 'service_name', 'start_date', 'end_date', 'amount_paid']
        st.dataframe(subscriptions[display_cols].head(10), use_container_width=True)

def show_client_management():
    st.header("Client Management")
    
    tab1, tab2 = st.tabs(["View Clients", "Add Client"])
    
    with tab1:
        clients = st.session_state.db_manager.get_clients()
        if len(clients) > 0:
            search_term = st.text_input("Search clients", placeholder="Enter name or email")
            if search_term:
                clients = clients[
                    clients['name'].str.contains(search_term, case=False, na=False) |
                    clients['email'].str.contains(search_term, case=False, na=False)
                ]
            st.dataframe(clients, use_container_width=True)
        else:
            st.info("No clients found. Add your first client!")
    
    with tab2:
        st.subheader("Add New Client")
        with st.form("add_client_form"):
            col1, col2 = st.columns(2)
            with col1:
                name = st.text_input("Client Name *", placeholder="Enter full name")
                email = st.text_input("Email Address *", placeholder="client@email.com")
            with col2:
                phone = st.text_input("Phone Number", placeholder="+91 9999999999")
                whatsapp = st.text_input("WhatsApp Number *", placeholder="+91 9999999999")
            
            notes = st.text_area("Additional Notes", placeholder="Any special information...")
            
            submitted = st.form_submit_button("Add Client", type="primary")
            
            if submitted and name and email and whatsapp:
                try:
                    conn = st.session_state.db_manager.get_connection()
                    cursor = conn.cursor()
                    cursor.execute(
                        "INSERT INTO clients (name, email, phone, whatsapp, notes) VALUES (?, ?, ?, ?, ?)",
                        (name, email, phone, whatsapp, notes)
                    )
                    conn.commit()
                    conn.close()
                    st.success(f"Client '{name}' added successfully!")
                    st.rerun()
                except sqlite3.IntegrityError:
                    st.error("Email already exists!")
            elif submitted:
                st.error("Name, Email, and WhatsApp number are required!")

def show_subscription_management():
    st.header("Subscription Management")
    
    tab1, tab2 = st.tabs(["Active Subscriptions", "Add Subscription"])
    
    with tab1:
        subscriptions = st.session_state.db_manager.get_active_subscriptions()
        if len(subscriptions) > 0:
            service_filter = st.selectbox("Filter by Service", ["All Services"] + list(subscriptions['service_name'].unique()))
            
            if service_filter != "All Services":
                subscriptions = subscriptions[subscriptions['service_name'] == service_filter]
            
            subscriptions['end_date_dt'] = pd.to_datetime(subscriptions['end_date'])
            subscriptions['days_remaining'] = (subscriptions['end_date_dt'] - pd.Timestamp.now()).dt.days
            
            display_cols = ['client_name', 'service_name', 'start_date', 'end_date', 'days_remaining', 'amount_paid']
            st.dataframe(subscriptions[display_cols], use_container_width=True)
        else:
            st.info("No active subscriptions found.")
    
    with tab2:
        st.subheader("Create New Subscription")
        
        clients = st.session_state.db_manager.get_clients()
        services = st.session_state.db_manager.get_services()
        
        if len(clients) > 0 and len(services) > 0:
            with st.form("add_subscription_form"):
                client_options = [f"{row['name']} ({row['email']})" for _, row in clients.iterrows()]
                selected_client = st.selectbox("Select Client *", ["Choose a client..."] + client_options)
                
                selected_service = st.selectbox("Select Service *", ["Choose a service..."] + services['name'].tolist())
                
                if selected_service != "Choose a service...":
                    service_data = services[services['name'] == selected_service].iloc[0]
                    st.info(f"Service: {service_data['description']} | Price: Rs {service_data['price']:,.0f} | Duration: {service_data['duration_days']} days")
                
                col1, col2 = st.columns(2)
                with col1:
                    start_date = st.date_input("Start Date *", value=datetime.now().date())
                    amount_paid = st.number_input("Amount Paid (Rs) *", 
                                                min_value=0.0,
                                                value=service_data['price'] if selected_service != "Choose a service..." else 0.0)
                with col2:
                    payment_methods = ["UPI", "Bank Transfer", "Credit Card", "Debit Card", "Cash", "Net Banking"]
                    payment_method = st.selectbox("Payment Method *", ["Select method..."] + payment_methods)
                    transaction_id = st.text_input("Transaction ID", placeholder="Enter transaction reference")
                
                submitted = st.form_submit_button("Create Subscription", type="primary")
                
                if submitted and selected_client != "Choose a client..." and selected_service != "Choose a service..." and payment_method != "Select method...":
                    client_email = selected_client.split('(')[1][:-1]
                    client_id = clients[clients['email'] == client_email].iloc[0]['id']
                    service_id = service_data['id']
                    end_date = start_date + timedelta(days=service_data['duration_days'])
                    
                    conn = st.session_state.db_manager.get_connection()
                    cursor = conn.cursor()
                    cursor.execute('''
                        INSERT INTO subscriptions 
                        (client_id, service_id, start_date, end_date, amount_paid, payment_method, transaction_id)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    ''', (client_id, service_id, start_date, end_date, amount_paid, payment_method, transaction_id))
                    conn.commit()
                    conn.close()
                    
                    st.success(f"Subscription created! Valid until {end_date}")
                    st.rerun()
                elif submitted:
                    st.error("Please fill all required fields!")
        else:
            st.warning("Please add clients and services first.")

def show_whatsapp_settings():
    st.header("WhatsApp Configuration")
    
    tab1, tab2 = st.tabs(["Settings", "Test & Send"])
    
    with tab1:
        st.subheader("WhatsApp API Configuration")
        
        with st.form("whatsapp_settings_form"):
            col1, col2 = st.columns(2)
            with col1:
                whatsapp_enabled = st.checkbox("Enable WhatsApp Notifications",
                                              value=st.session_state.config_manager.get('whatsapp.enabled'))
                api_url = st.text_input("WhatsApp API URL",
                                       value=st.session_state.config_manager.get('whatsapp.api_url'),
                                       placeholder="https://api.whatsapp.example.com/send")
            with col2:
                api_key = st.text_input("WhatsApp API Key", 
                                       type="password",
                                       value=st.session_state.config_manager.get('whatsapp.api_key'),
                                       placeholder="Your API key")
            
            st.info("""
            WhatsApp API Setup:
            - Use services like Twilio, MessageBird, or WhatsApp Business API
            - Get API URL and authentication key from your provider
            - Phone numbers should include country code (+91 for India)
            """)
            
            submitted = st.form_submit_button("Save WhatsApp Settings", type="primary")
            
            if submitted:
                st.session_state.config_manager.set('whatsapp.enabled', whatsapp_enabled)
                st.session_state.config_manager.set('whatsapp.api_url', api_url)
                st.session_state.config_manager.set('whatsapp.api_key', api_key)
                st.session_state.config_manager.save_config()
                st.success("WhatsApp settings saved!")
                st.rerun()
    
    with tab2:
        st.subheader("Test WhatsApp & Send Custom Messages")
        
        if st.session_state.config_manager.get('whatsapp.enabled'):
            col1, col2 = st.columns(2)
            
            with col1:
                st.write("**Test Message**")
                test_phone = st.text_input("Test Phone Number", placeholder="+919999999999")
                if st.button("Send Test Message"):
                    if test_phone:
                        test_message = f"Hello! This is a test message from {st.session_state.config_manager.get('business.name')} Client Manager."
                        success = st.session_state.notification_manager.send_whatsapp_notification(test_phone, test_message)
                        if success:
                            st.success("Test message sent successfully!")
                        else:
                            st.error("Failed to send test message. Check your API settings.")
                    else:
                        st.error("Please enter a phone number")
            
            with col2:
                st.write("**Send Expiry Reminders**")
                expiring = st.session_state.db_manager.get_expiring_subscriptions(1)
                st.write(f"Clients expiring tomorrow: {len(expiring)}")
                
                if len(expiring) > 0:
                    if st.button("Send All Expiry Reminders", type="primary"):
                        st.session_state.notification_manager.send_expiry_notifications()
                        st.success(f"Sent reminders to {len(expiring)} clients!")
                else:
                    st.info("No subscriptions expiring tomorrow")
            
            st.subheader("Custom Message")
            with st.form("custom_message_form"):
                clients = st.session_state.db_manager.get_clients()
                if len(clients) > 0:
                    client_options = ["All Clients"] + [f"{row['name']} ({row['whatsapp']})" for _, row in clients.iterrows() if row['whatsapp']]
                    selected_recipients = st.multiselect("Select Recipients", client_options)
                    
                    message = st.text_area("Message", 
                                         placeholder="Enter your custom message...\n\nUse {client_name} for personalization",
                                         height=100)
                    
                    send_custom = st.form_submit_button("Send Custom Message")
                    
                    if send_custom and message and selected_recipients:
                        sent_count = 0
                        
                        if "All Clients" in selected_recipients:
                            target_clients = clients[clients['whatsapp'].notna() & (clients['whatsapp'] != '')]
                        else:
                            phones = [r.split('(')[1][:-1] for r in selected_recipients if '(' in r]
                            target_clients = clients[clients['whatsapp'].isin(phones)]
                        
                        for _, client in target_clients.iterrows():
                            personalized_message = message.replace('{client_name}', client['name'])
                            if st.session_state.notification_manager.send_whatsapp_notification(client['whatsapp'], personalized_message):
                                sent_count += 1
                        
                        st.success(f"Custom message sent to {sent_count} clients!")
        else:
            st.warning("WhatsApp notifications are disabled. Enable them in Settings first.")

def run_streamlit_app():
    init_streamlit_app()
    show_header()
    
    st.sidebar.title("Navigation")
    pages = ["Dashboard", "Client Management", "Subscription Management", "WhatsApp Settings"]
    
    business_name = st.session_state.config_manager.get('business.name')
    whatsapp_status = st.session_state.config_manager.get('whatsapp.enabled')
    
    st.sidebar.markdown(f"""
    ---
    **{business_name}**  
    WhatsApp-Only Version
    
    WhatsApp: {'Enabled' if whatsapp_status else 'Disabled'}
    """)
    
    selected_page = st.sidebar.selectbox("Select Page", pages)
    
    if selected_page == "Dashboard":
        show_dashboard()
    elif selected_page == "Client Management":
        show_client_management()
    elif selected_page == "Subscription Management":
        show_subscription_management()
    elif selected_page == "WhatsApp Settings":
        show_whatsapp_settings()

def main():
    parser = argparse.ArgumentParser(description='NYZTrade Premium Client Manager - WhatsApp Only')
    parser.add_argument('--mode', choices=['app'], default='app', help='Mode to run in')
    
    args = parser.parse_args()
    
    if args.mode == 'app':
        run_streamlit_app()

if __name__ == "__main__":
    main()
