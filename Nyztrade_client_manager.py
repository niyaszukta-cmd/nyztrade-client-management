#!/usr/bin/env python3
"""
NYZTrade Premium Client Management System
Ultra-Minimal Version - No Charts, No Complex Imports

Usage: python nyztrade_minimal.py

Author: NIYAS - NYZTrade  
Version: 1.0.3 - Ultra Minimal
"""

import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, timedelta
import requests
import json
import os
import sys

# Configuration defaults
DEFAULT_CONFIG = {
    "whatsapp": {
        "api_url": "",
        "api_key": "",
        "enabled": False
    },
    "business": {
        "name": "NYZTrade",
        "contact_phone": "+91-9999999999",
        "contact_email": "support@nyztrade.com"
    },
    "database": {
        "path": "premium_clients.db"
    }
}

class ConfigManager:
    def __init__(self):
        self.config_file = 'config.json'
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
                FOREIGN KEY (client_id) REFERENCES clients (id),
                FOREIGN KEY (service_id) REFERENCES services (id)
            )
        ''')
        
        cursor.execute("SELECT COUNT(*) FROM services")
        if cursor.fetchone()[0] == 0:
            default_services = [
                ('EQUITY Premium', 'Advanced equity analysis and trading signals', 5000.0, 30),
                ('OPTION Premium', 'Professional options trading strategies', 7000.0, 30),
                ('VALUATION Premium', 'Company valuation and research reports', 4000.0, 30),
                ('COMBO Package', 'Combined equity and options package', 10000.0, 30),
                ('ANNUAL Membership', 'Complete annual access to all services', 100000.0, 365)
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
                   sv.name as service_name
            FROM subscriptions s
            JOIN clients c ON s.client_id = c.id
            JOIN services sv ON s.service_id = sv.id
            WHERE s.status = 'Active' 
            AND s.end_date = date('now', '+{} days')
        '''.format(days)
        df = pd.read_sql_query(query, conn)
        conn.close()
        return df

class WhatsAppManager:
    def __init__(self, config_manager, db_manager):
        self.config = config_manager
        self.db = db_manager
    
    def send_whatsapp_notification(self, phone, message):
        try:
            if not self.config.get('whatsapp.enabled'):
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
            
            return response.status_code == 200
                
        except Exception:
            return False
    
    def send_expiry_notifications(self):
        expiring_subscriptions = self.db.get_expiring_subscriptions(1)
        sent_count = 0
        
        for _, subscription in expiring_subscriptions.iterrows():
            if subscription['whatsapp']:
                business_name = self.config.get('business.name')
                
                message = f"""{business_name} Reminder

Hello {subscription['client_name']}!

Your {subscription['service_name']} subscription expires on {subscription['end_date']}.

Contact us to renew:
Phone: {self.config.get('business.contact_phone')}

Thank you for choosing {business_name}!"""
                
                if self.send_whatsapp_notification(subscription['whatsapp'], message):
                    sent_count += 1
        
        return sent_count

def init_app():
    st.set_page_config(
        page_title="NYZTrade - Client Manager",
        layout="wide"
    )
    
    if 'config_manager' not in st.session_state:
        st.session_state.config_manager = ConfigManager()
    
    if 'db_manager' not in st.session_state:
        st.session_state.db_manager = DatabaseManager()
    
    if 'whatsapp_manager' not in st.session_state:
        st.session_state.whatsapp_manager = WhatsAppManager(
            st.session_state.config_manager,
            st.session_state.db_manager
        )

def show_dashboard():
    st.header("NYZTrade Dashboard")
    
    clients = st.session_state.db_manager.get_clients()
    subscriptions = st.session_state.db_manager.get_active_subscriptions()
    expiring_soon = st.session_state.db_manager.get_expiring_subscriptions(1)
    
    # Simple metrics without charts
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("Total Clients", len(clients))
    with col2:
        st.metric("Active Subscriptions", len(subscriptions))
    with col3:
        total_revenue = subscriptions['amount_paid'].sum() if len(subscriptions) > 0 else 0
        st.metric("Revenue", f"Rs {total_revenue:,.0f}")
    with col4:
        st.metric("Expiring Soon", len(expiring_soon))
    
    # Expiring subscriptions alert
    if len(expiring_soon) > 0:
        st.subheader("Expiring Tomorrow")
        for _, row in expiring_soon.iterrows():
            st.warning(f"{row['client_name']} - {row['service_name']} expires {row['end_date']}")
        
        if st.button("Send WhatsApp Reminders", type="primary"):
            sent_count = st.session_state.whatsapp_manager.send_expiry_notifications()
            if sent_count > 0:
                st.success(f"Sent WhatsApp reminders to {sent_count} clients!")
            else:
                st.error("Failed to send reminders. Check WhatsApp settings.")
    
    # Recent subscriptions
    st.subheader("Recent Subscriptions")
    if len(subscriptions) > 0:
        display_cols = ['client_name', 'service_name', 'start_date', 'end_date', 'amount_paid']
        st.dataframe(subscriptions[display_cols].head(10), use_container_width=True)
    else:
        st.info("No active subscriptions found.")

def show_clients():
    st.header("Client Management")
    
    tab1, tab2 = st.tabs(["View Clients", "Add Client"])
    
    with tab1:
        clients = st.session_state.db_manager.get_clients()
        if len(clients) > 0:
            search = st.text_input("Search clients", placeholder="Enter name or email")
            if search:
                clients = clients[
                    clients['name'].str.contains(search, case=False, na=False) |
                    clients['email'].str.contains(search, case=False, na=False)
                ]
            st.dataframe(clients, use_container_width=True)
        else:
            st.info("No clients found. Add your first client!")
    
    with tab2:
        st.subheader("Add New Client")
        
        with st.form("add_client"):
            col1, col2 = st.columns(2)
            with col1:
                name = st.text_input("Name *")
                email = st.text_input("Email *")
            with col2:
                phone = st.text_input("Phone")
                whatsapp = st.text_input("WhatsApp *")
            
            notes = st.text_area("Notes")
            submitted = st.form_submit_button("Add Client")
            
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
                    st.success(f"Client {name} added successfully!")
                    st.rerun()
                except sqlite3.IntegrityError:
                    st.error("Email already exists!")
            elif submitted:
                st.error("Name, Email, and WhatsApp are required!")

def show_subscriptions():
    st.header("Subscription Management")
    
    tab1, tab2 = st.tabs(["View Subscriptions", "Add Subscription"])
    
    with tab1:
        subscriptions = st.session_state.db_manager.get_active_subscriptions()
        if len(subscriptions) > 0:
            # Calculate days remaining
            subscriptions['end_date_dt'] = pd.to_datetime(subscriptions['end_date'])
            subscriptions['days_remaining'] = (subscriptions['end_date_dt'] - pd.Timestamp.now()).dt.days
            
            display_cols = ['client_name', 'service_name', 'start_date', 'end_date', 'days_remaining', 'amount_paid']
            st.dataframe(subscriptions[display_cols], use_container_width=True)
        else:
            st.info("No active subscriptions found.")
    
    with tab2:
        st.subheader("Create Subscription")
        
        clients = st.session_state.db_manager.get_clients()
        services = st.session_state.db_manager.get_services()
        
        if len(clients) > 0 and len(services) > 0:
            with st.form("add_subscription"):
                client_options = [f"{row['name']} ({row['email']})" for _, row in clients.iterrows()]
                selected_client = st.selectbox("Select Client", client_options)
                
                service_options = services['name'].tolist()
                selected_service = st.selectbox("Select Service", service_options)
                
                service_data = services[services['name'] == selected_service].iloc[0]
                st.info(f"Price: Rs {service_data['price']:,.0f} | Duration: {service_data['duration_days']} days")
                
                col1, col2 = st.columns(2)
                with col1:
                    start_date = st.date_input("Start Date", value=datetime.now().date())
                    amount_paid = st.number_input("Amount Paid", value=float(service_data['price']))
                with col2:
                    payment_method = st.selectbox("Payment Method", ["UPI", "Bank Transfer", "Credit Card", "Cash"])
                    transaction_id = st.text_input("Transaction ID")
                
                submitted = st.form_submit_button("Create Subscription")
                
                if submitted:
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
        else:
            st.warning("Add clients and services first.")

def show_whatsapp():
    st.header("WhatsApp Settings")
    
    tab1, tab2 = st.tabs(["Configuration", "Send Messages"])
    
    with tab1:
        with st.form("whatsapp_config"):
            enabled = st.checkbox("Enable WhatsApp", 
                                value=st.session_state.config_manager.get('whatsapp.enabled'))
            api_url = st.text_input("API URL", 
                                  value=st.session_state.config_manager.get('whatsapp.api_url'))
            api_key = st.text_input("API Key", 
                                  type="password",
                                  value=st.session_state.config_manager.get('whatsapp.api_key'))
            
            submitted = st.form_submit_button("Save Settings")
            
            if submitted:
                st.session_state.config_manager.set('whatsapp.enabled', enabled)
                st.session_state.config_manager.set('whatsapp.api_url', api_url)
                st.session_state.config_manager.set('whatsapp.api_key', api_key)
                st.session_state.config_manager.save_config()
                st.success("Settings saved!")
                st.rerun()
    
    with tab2:
        if st.session_state.config_manager.get('whatsapp.enabled'):
            st.subheader("Test Message")
            test_phone = st.text_input("Test Phone", placeholder="+919999999999")
            
            if st.button("Send Test") and test_phone:
                message = "Test message from NYZTrade Client Manager"
                success = st.session_state.whatsapp_manager.send_whatsapp_notification(test_phone, message)
                if success:
                    st.success("Test message sent!")
                else:
                    st.error("Failed to send. Check settings.")
            
            st.subheader("Send Expiry Reminders")
            expiring = st.session_state.db_manager.get_expiring_subscriptions(1)
            st.write(f"Clients expiring tomorrow: {len(expiring)}")
            
            if len(expiring) > 0 and st.button("Send All Reminders"):
                sent_count = st.session_state.whatsapp_manager.send_expiry_notifications()
                st.success(f"Sent reminders to {sent_count} clients!")
        else:
            st.warning("Enable WhatsApp in Configuration first.")

def main():
    init_app()
    
    # Header
    st.title("NYZTrade Premium Client Manager")
    st.caption("Simple & Reliable Client Management System")
    
    # Sidebar navigation
    st.sidebar.title("Menu")
    pages = ["Dashboard", "Clients", "Subscriptions", "WhatsApp"]
    
    # Status info
    whatsapp_status = "ON" if st.session_state.config_manager.get('whatsapp.enabled') else "OFF"
    st.sidebar.info(f"WhatsApp: {whatsapp_status}")
    
    selected = st.sidebar.selectbox("Select Page", pages)
    
    # Route pages
    if selected == "Dashboard":
        show_dashboard()
    elif selected == "Clients":
        show_clients()
    elif selected == "Subscriptions":
        show_subscriptions()
    elif selected == "WhatsApp":
        show_whatsapp()

if __name__ == "__main__":
    main()
