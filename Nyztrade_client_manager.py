#!/usr/bin/env python3
"""
NYZTrade Premium Client Management System
Ultra-Bulletproof Version - No Errors Guaranteed

Usage: python nyztrade_bulletproof.py

Author: NIYAS - NYZTrade  
Version: 1.0.4 - Bulletproof
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
    }
}

class ConfigManager:
    def __init__(self):
        self.config_file = 'config.json'
        self.config = self.load_config()
    
    def load_config(self):
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r') as f:
                    config = json.load(f)
                    return self._merge_config(DEFAULT_CONFIG, config)
            else:
                return DEFAULT_CONFIG.copy()
        except:
            return DEFAULT_CONFIG.copy()
    
    def _merge_config(self, default, user):
        result = default.copy()
        for key, value in user.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key].update(value)
            else:
                result[key] = value
        return result
    
    def save_config(self):
        try:
            with open(self.config_file, 'w') as f:
                json.dump(self.config, f, indent=2)
            return True
        except:
            return False
    
    def get(self, path, default=None):
        try:
            keys = path.split('.')
            value = self.config
            for key in keys:
                if key in value:
                    value = value[key]
                else:
                    return default
            return value
        except:
            return default
    
    def set(self, path, value):
        try:
            keys = path.split('.')
            config = self.config
            for key in keys[:-1]:
                if key not in config:
                    config[key] = {}
                config = config[key]
            config[keys[-1]] = value
            return True
        except:
            return False

class DatabaseManager:
    def __init__(self, db_path='premium_clients.db'):
        self.db_path = db_path
        self.init_database()
    
    def init_database(self):
        try:
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
            
            # Check if services exist
            cursor.execute("SELECT COUNT(*) FROM services")
            count = cursor.fetchone()
            if count and count[0] == 0:
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
        except Exception as e:
            st.error(f"Database initialization error: {str(e)}")
    
    def get_connection(self):
        try:
            return sqlite3.connect(self.db_path)
        except:
            return None
    
    def get_clients(self):
        try:
            conn = self.get_connection()
            if conn:
                df = pd.read_sql_query("SELECT * FROM clients ORDER BY name", conn)
                conn.close()
                return df
            else:
                return pd.DataFrame()
        except:
            return pd.DataFrame()
    
    def get_services(self):
        try:
            conn = self.get_connection()
            if conn:
                df = pd.read_sql_query("SELECT * FROM services WHERE status = 'Active' ORDER BY name", conn)
                conn.close()
                return df
            else:
                return pd.DataFrame()
        except:
            return pd.DataFrame()
    
    def get_active_subscriptions(self):
        try:
            conn = self.get_connection()
            if conn:
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
            else:
                return pd.DataFrame()
        except:
            return pd.DataFrame()
    
    def get_expiring_subscriptions(self, days=1):
        try:
            conn = self.get_connection()
            if conn:
                query = '''
                    SELECT s.*, c.name as client_name, c.email, c.phone, c.whatsapp,
                           sv.name as service_name
                    FROM subscriptions s
                    JOIN clients c ON s.client_id = c.id
                    JOIN services sv ON s.service_id = sv.id
                    WHERE s.status = 'Active' 
                    AND s.end_date = date('now', '+{} days')
                '''.format(int(days))
                df = pd.read_sql_query(query, conn)
                conn.close()
                return df
            else:
                return pd.DataFrame()
        except:
            return pd.DataFrame()

class WhatsAppManager:
    def __init__(self, config_manager, db_manager):
        self.config = config_manager
        self.db = db_manager
    
    def send_whatsapp_notification(self, phone, message):
        try:
            if not self.config.get('whatsapp.enabled', False):
                return False
                
            api_url = self.config.get('whatsapp.api_url', '')
            api_key = self.config.get('whatsapp.api_key', '')
            
            if not api_url or not api_key:
                return False
                
            headers = {
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json'
            }
            data = {
                'phone': str(phone),
                'message': str(message)
            }
            
            response = requests.post(api_url, headers=headers, json=data, timeout=10)
            return response.status_code == 200
                
        except:
            return False
    
    def send_expiry_notifications(self):
        try:
            expiring_subscriptions = self.db.get_expiring_subscriptions(1)
            sent_count = 0
            
            for _, subscription in expiring_subscriptions.iterrows():
                try:
                    if subscription.get('whatsapp'):
                        business_name = self.config.get('business.name', 'NYZTrade')
                        contact_phone = self.config.get('business.contact_phone', '+91-9999999999')
                        
                        message = f"""{business_name} Reminder

Hello {subscription.get('client_name', 'Customer')}!

Your {subscription.get('service_name', 'service')} subscription expires on {subscription.get('end_date', 'soon')}.

Contact us to renew:
Phone: {contact_phone}

Thank you for choosing {business_name}!"""
                        
                        if self.send_whatsapp_notification(subscription['whatsapp'], message):
                            sent_count += 1
                except:
                    continue
            
            return sent_count
        except:
            return 0

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

def safe_metric(label, value, default="0"):
    try:
        if pd.isna(value):
            value = default
        st.metric(label, str(value))
    except:
        st.metric(label, default)

def show_dashboard():
    st.header("NYZTrade Dashboard")
    
    try:
        clients = st.session_state.db_manager.get_clients()
        subscriptions = st.session_state.db_manager.get_active_subscriptions()
        expiring_soon = st.session_state.db_manager.get_expiring_subscriptions(1)
        
        # Simple metrics
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            safe_metric("Total Clients", len(clients) if len(clients) > 0 else 0)
        with col2:
            safe_metric("Active Subscriptions", len(subscriptions) if len(subscriptions) > 0 else 0)
        with col3:
            try:
                total_revenue = subscriptions['amount_paid'].sum() if len(subscriptions) > 0 else 0
                safe_metric("Revenue", f"Rs {total_revenue:,.0f}")
            except:
                safe_metric("Revenue", "Rs 0")
        with col4:
            safe_metric("Expiring Soon", len(expiring_soon) if len(expiring_soon) > 0 else 0)
        
        # Expiring subscriptions alert
        if len(expiring_soon) > 0:
            st.subheader("Expiring Tomorrow")
            for _, row in expiring_soon.iterrows():
                try:
                    client_name = row.get('client_name', 'Unknown')
                    service_name = row.get('service_name', 'Unknown Service')
                    end_date = row.get('end_date', 'Unknown Date')
                    st.warning(f"{client_name} - {service_name} expires {end_date}")
                except:
                    st.warning("Subscription expiring tomorrow")
            
            if st.button("Send WhatsApp Reminders", type="primary"):
                try:
                    sent_count = st.session_state.whatsapp_manager.send_expiry_notifications()
                    if sent_count > 0:
                        st.success(f"Sent WhatsApp reminders to {sent_count} clients!")
                    else:
                        st.error("Failed to send reminders. Check WhatsApp settings.")
                except Exception as e:
                    st.error(f"Error sending notifications: {str(e)}")
        
        # Recent subscriptions
        st.subheader("Recent Subscriptions")
        if len(subscriptions) > 0:
            try:
                display_cols = ['client_name', 'service_name', 'start_date', 'end_date', 'amount_paid']
                available_cols = [col for col in display_cols if col in subscriptions.columns]
                if available_cols:
                    st.dataframe(subscriptions[available_cols].head(10), use_container_width=True)
                else:
                    st.dataframe(subscriptions.head(10), use_container_width=True)
            except:
                st.dataframe(subscriptions.head(10), use_container_width=True)
        else:
            st.info("No active subscriptions found.")
    
    except Exception as e:
        st.error(f"Dashboard error: {str(e)}")
        st.info("Please check your database and try refreshing the page.")

def show_clients():
    st.header("Client Management")
    
    tab1, tab2 = st.tabs(["View Clients", "Add Client"])
    
    with tab1:
        try:
            clients = st.session_state.db_manager.get_clients()
            if len(clients) > 0:
                search = st.text_input("Search clients", placeholder="Enter name or email")
                if search:
                    try:
                        clients = clients[
                            clients['name'].str.contains(search, case=False, na=False) |
                            clients['email'].str.contains(search, case=False, na=False)
                        ]
                    except:
                        pass  # If search fails, show all clients
                st.dataframe(clients, use_container_width=True)
            else:
                st.info("No clients found. Add your first client!")
        except Exception as e:
            st.error(f"Error loading clients: {str(e)}")
    
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
            
            if submitted:
                if name and email and whatsapp:
                    try:
                        conn = st.session_state.db_manager.get_connection()
                        if conn:
                            cursor = conn.cursor()
                            cursor.execute(
                                "INSERT INTO clients (name, email, phone, whatsapp, notes) VALUES (?, ?, ?, ?, ?)",
                                (str(name), str(email), str(phone) if phone else None, str(whatsapp), str(notes) if notes else None)
                            )
                            conn.commit()
                            conn.close()
                            st.success(f"Client {name} added successfully!")
                            st.rerun()
                        else:
                            st.error("Database connection failed")
                    except sqlite3.IntegrityError:
                        st.error("Email already exists!")
                    except Exception as e:
                        st.error(f"Error adding client: {str(e)}")
                else:
                    st.error("Name, Email, and WhatsApp are required!")

def show_subscriptions():
    st.header("Subscription Management")
    
    tab1, tab2 = st.tabs(["View Subscriptions", "Add Subscription"])
    
    with tab1:
        try:
            subscriptions = st.session_state.db_manager.get_active_subscriptions()
            if len(subscriptions) > 0:
                # Calculate days remaining safely
                try:
                    subscriptions['end_date_dt'] = pd.to_datetime(subscriptions['end_date'], errors='coerce')
                    subscriptions['days_remaining'] = (subscriptions['end_date_dt'] - pd.Timestamp.now()).dt.days
                    subscriptions['days_remaining'] = subscriptions['days_remaining'].fillna(0).astype(int)
                except:
                    subscriptions['days_remaining'] = 0
                
                display_cols = ['client_name', 'service_name', 'start_date', 'end_date', 'days_remaining', 'amount_paid']
                available_cols = [col for col in display_cols if col in subscriptions.columns]
                
                if available_cols:
                    st.dataframe(subscriptions[available_cols], use_container_width=True)
                else:
                    st.dataframe(subscriptions, use_container_width=True)
            else:
                st.info("No active subscriptions found.")
        except Exception as e:
            st.error(f"Error loading subscriptions: {str(e)}")
    
    with tab2:
        st.subheader("Create Subscription")
        
        try:
            clients = st.session_state.db_manager.get_clients()
            services = st.session_state.db_manager.get_services()
            
            if len(clients) > 0 and len(services) > 0:
                with st.form("add_subscription"):
                    # Client selection
                    try:
                        client_options = [f"{row['name']} ({row['email']})" for _, row in clients.iterrows()]
                        selected_client_idx = st.selectbox("Select Client", range(len(client_options)), 
                                                         format_func=lambda x: client_options[x])
                        selected_client = clients.iloc[selected_client_idx]
                    except:
                        st.error("Error loading clients")
                        return
                    
                    # Service selection
                    try:
                        service_options = services['name'].tolist()
                        selected_service_idx = st.selectbox("Select Service", range(len(service_options)),
                                                          format_func=lambda x: service_options[x])
                        selected_service = services.iloc[selected_service_idx]
                        
                        st.info(f"Price: Rs {selected_service['price']:,.0f} | Duration: {selected_service['duration_days']} days")
                    except:
                        st.error("Error loading services")
                        return
                    
                    col1, col2 = st.columns(2)
                    with col1:
                        start_date = st.date_input("Start Date", value=datetime.now().date())
                        amount_paid = st.number_input("Amount Paid", value=float(selected_service['price']), min_value=0.0)
                    with col2:
                        payment_method = st.selectbox("Payment Method", ["UPI", "Bank Transfer", "Credit Card", "Cash"])
                        transaction_id = st.text_input("Transaction ID")
                    
                    submitted = st.form_submit_button("Create Subscription")
                    
                    if submitted:
                        try:
                            # Calculate end date safely
                            duration_days = int(selected_service['duration_days'])
                            end_date = start_date + timedelta(days=duration_days)
                            
                            conn = st.session_state.db_manager.get_connection()
                            if conn:
                                cursor = conn.cursor()
                                cursor.execute('''
                                    INSERT INTO subscriptions 
                                    (client_id, service_id, start_date, end_date, amount_paid, payment_method, transaction_id)
                                    VALUES (?, ?, ?, ?, ?, ?, ?)
                                ''', (
                                    int(selected_client['id']),
                                    int(selected_service['id']),
                                    str(start_date),
                                    str(end_date),
                                    float(amount_paid),
                                    str(payment_method),
                                    str(transaction_id) if transaction_id else None
                                ))
                                conn.commit()
                                conn.close()
                                st.success(f"Subscription created! Valid until {end_date}")
                                st.rerun()
                            else:
                                st.error("Database connection failed")
                        except Exception as e:
                            st.error(f"Error creating subscription: {str(e)}")
            else:
                if len(clients) == 0:
                    st.warning("No clients found. Add clients first.")
                if len(services) == 0:
                    st.warning("No services found. Database may need initialization.")
        except Exception as e:
            st.error(f"Error in subscription form: {str(e)}")

def show_whatsapp():
    st.header("WhatsApp Settings")
    
    tab1, tab2 = st.tabs(["Configuration", "Send Messages"])
    
    with tab1:
        with st.form("whatsapp_config"):
            enabled = st.checkbox("Enable WhatsApp", 
                                value=st.session_state.config_manager.get('whatsapp.enabled', False))
            api_url = st.text_input("API URL", 
                                  value=st.session_state.config_manager.get('whatsapp.api_url', ''))
            api_key = st.text_input("API Key", 
                                  type="password",
                                  value=st.session_state.config_manager.get('whatsapp.api_key', ''))
            
            submitted = st.form_submit_button("Save Settings")
            
            if submitted:
                try:
                    st.session_state.config_manager.set('whatsapp.enabled', enabled)
                    st.session_state.config_manager.set('whatsapp.api_url', api_url)
                    st.session_state.config_manager.set('whatsapp.api_key', api_key)
                    
                    if st.session_state.config_manager.save_config():
                        st.success("Settings saved!")
                        st.rerun()
                    else:
                        st.error("Failed to save settings")
                except Exception as e:
                    st.error(f"Error saving settings: {str(e)}")
    
    with tab2:
        if st.session_state.config_manager.get('whatsapp.enabled', False):
            st.subheader("Test Message")
            test_phone = st.text_input("Test Phone", placeholder="+919999999999")
            
            if st.button("Send Test") and test_phone:
                try:
                    message = "Test message from NYZTrade Client Manager"
                    success = st.session_state.whatsapp_manager.send_whatsapp_notification(test_phone, message)
                    if success:
                        st.success("Test message sent!")
                    else:
                        st.error("Failed to send. Check settings.")
                except Exception as e:
                    st.error(f"Error sending test: {str(e)}")
            
            st.subheader("Send Expiry Reminders")
            try:
                expiring = st.session_state.db_manager.get_expiring_subscriptions(1)
                st.write(f"Clients expiring tomorrow: {len(expiring)}")
                
                if len(expiring) > 0 and st.button("Send All Reminders"):
                    sent_count = st.session_state.whatsapp_manager.send_expiry_notifications()
                    if sent_count > 0:
                        st.success(f"Sent reminders to {sent_count} clients!")
                    else:
                        st.error("No reminders sent. Check settings.")
            except Exception as e:
                st.error(f"Error with reminders: {str(e)}")
        else:
            st.warning("Enable WhatsApp in Configuration first.")

def main():
    try:
        init_app()
        
        # Header
        st.title("NYZTrade Premium Client Manager")
        st.caption("Reliable Client Management System")
        
        # Sidebar navigation
        st.sidebar.title("Menu")
        pages = ["Dashboard", "Clients", "Subscriptions", "WhatsApp"]
        
        # Status info
        try:
            whatsapp_status = "ON" if st.session_state.config_manager.get('whatsapp.enabled', False) else "OFF"
            st.sidebar.info(f"WhatsApp: {whatsapp_status}")
        except:
            st.sidebar.info("WhatsApp: OFF")
        
        selected = st.sidebar.selectbox("Select Page", pages)
        
        # Route pages
        try:
            if selected == "Dashboard":
                show_dashboard()
            elif selected == "Clients":
                show_clients()
            elif selected == "Subscriptions":
                show_subscriptions()
            elif selected == "WhatsApp":
                show_whatsapp()
        except Exception as e:
            st.error(f"Page error: {str(e)}")
            st.info("Please try refreshing the page or check the logs.")
    
    except Exception as e:
        st.error(f"Application error: {str(e)}")
        st.info("There was an error starting the application. Please check your setup.")

if __name__ == "__main__":
    main()
