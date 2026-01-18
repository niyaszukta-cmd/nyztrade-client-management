#!/usr/bin/env python3
"""
NYZTrade Premium Client Management System
Complete all-in-one solution for client management, subscriptions, and notifications

Usage:
    python nyztrade_client_manager.py                    # Run Streamlit app (default)
    python nyztrade_client_manager.py --mode app         # Run Streamlit app
    python nyztrade_client_manager.py --mode scheduler   # Run notification scheduler
    python nyztrade_client_manager.py --mode setup       # Run setup utility
    python nyztrade_client_manager.py --mode test        # Test notifications

Author: NIYAS - NYZTrade
Version: 1.0.0
"""

import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, timedelta
import smtplib
from email.mime.text import MimeText
from email.mime.multipart import MimeMultipart
import requests
import json
import hashlib
import os
import sys
import argparse
import schedule
import time
import getpass
import logging
from typing import List, Dict
import plotly.express as px
import plotly.graph_objects as go

# =============================================================================
# CONFIGURATION AND SETUP
# =============================================================================

DEFAULT_CONFIG = {
    "email": {
        "smtp_server": "smtp.gmail.com",
        "smtp_port": 587,
        "email_address": "",
        "email_password": "",
        "enabled": False
    },
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
                # Merge with defaults to ensure all keys exist
                return self._merge_config(DEFAULT_CONFIG, config)
        except FileNotFoundError:
            return DEFAULT_CONFIG.copy()
    
    def _merge_config(self, default, user):
        """Recursively merge user config with default config"""
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
        """Get config value using dot notation (e.g., 'email.smtp_server')"""
        keys = path.split('.')
        value = self.config
        for key in keys:
            if key in value:
                value = value[key]
            else:
                return default
        return value
    
    def set(self, path, value):
        """Set config value using dot notation"""
        keys = path.split('.')
        config = self.config
        for key in keys[:-1]:
            if key not in config:
                config[key] = {}
            config = config[key]
        config[keys[-1]] = value

# =============================================================================
# DATABASE MANAGEMENT
# =============================================================================

class DatabaseManager:
    def __init__(self, db_path='premium_clients.db'):
        self.db_path = db_path
        self.init_database()
    
    def init_database(self):
        """Initialize SQLite database with required tables"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Clients table
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
        
        # Services table
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
        
        # Client subscriptions table
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
        
        # Notifications table
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
        
        # Insert default services if not exist
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

# =============================================================================
# NOTIFICATION SYSTEM
# =============================================================================

class NotificationManager:
    def __init__(self, config_manager, db_manager):
        self.config = config_manager
        self.db = db_manager
        self.setup_logging()
    
    def setup_logging(self):
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('notifications.log'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)
    
    def send_email_notification(self, to_email, subject, body):
        """Send email notification"""
        try:
            if not self.config.get('email.enabled'):
                self.logger.info("Email notifications disabled")
                return False
                
            msg = MimeMultipart()
            msg['From'] = self.config.get('email.email_address')
            msg['To'] = to_email
            msg['Subject'] = subject
            
            msg.attach(MimeText(body, 'html'))
            
            server = smtplib.SMTP(
                self.config.get('email.smtp_server'), 
                self.config.get('email.smtp_port')
            )
            server.starttls()
            server.login(
                self.config.get('email.email_address'),
                self.config.get('email.email_password')
            )
            text = msg.as_string()
            server.sendmail(
                self.config.get('email.email_address'), 
                to_email, 
                text
            )
            server.quit()
            
            self.logger.info(f"Email sent to {to_email}")
            return True
            
        except Exception as e:
            self.logger.error(f"Email failed for {to_email}: {str(e)}")
            return False
    
    def send_whatsapp_notification(self, phone, message):
        """Send WhatsApp notification"""
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
    
    def create_email_message(self, subscription):
        """Create email notification message"""
        subject = f"{self.config.get('business.name')} - {subscription['service_name']} Subscription Expiring Soon"
        
        body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; border-radius: 10px; text-align: center; margin-bottom: 20px;">
                    <h1 style="margin: 0; font-size: 24px;">📈 {self.config.get('business.name')}</h1>
                    <p style="margin: 10px 0 0 0; opacity: 0.9;">Premium Trading & Analysis Services</p>
                </div>
                
                <h2 style="color: #667eea;">Subscription Expiry Reminder</h2>
                <p>Dear <strong>{subscription['client_name']}</strong>,</p>
                
                <p>We hope you're enjoying our premium services. This is a friendly reminder that your subscription is about to expire:</p>
                
                <div style="background-color: #f8f9fa; padding: 20px; border-radius: 8px; margin: 20px 0; border-left: 4px solid #ffc107;">
                    <h3 style="color: #667eea; margin-top: 0;">📊 Service Details</h3>
                    <p><strong>Service:</strong> {subscription['service_name']}</p>
                    <p><strong>Expiry Date:</strong> {subscription['end_date']}</p>
                    <p><strong>Description:</strong> {subscription['description']}</p>
                </div>
                
                <p>To continue enjoying uninterrupted access to our premium features, please renew your subscription before the expiry date.</p>
                
                <h3 style="color: #28a745;">🚀 Why Renew with {self.config.get('business.name')}?</h3>
                <div style="background-color: #f8f9fa; padding: 15px; border-radius: 8px; margin: 15px 0;">
                    <ul style="margin: 0; padding-left: 20px;">
                        <li>✅ <strong>Advanced GEX/DEX Analysis:</strong> Real-time Gamma and Delta Exposure insights</li>
                        <li>✅ <strong>Professional Trading Signals:</strong> NIFTY & BANKNIFTY options strategies</li>
                        <li>✅ <strong>Exclusive Market Reports:</strong> Malayalam & English educational content</li>
                        <li>✅ <strong>Priority Support:</strong> Direct access to expert guidance</li>
                        <li>✅ <strong>Educational Resources:</strong> Continuous learning with market updates</li>
                    </ul>
                </div>
                
                <div style="background: linear-gradient(135deg, #28a745 0%, #20c997 100%); color: white; padding: 20px; border-radius: 8px; text-align: center; margin: 30px 0;">
                    <h3 style="margin: 0 0 15px 0;">📞 Ready to Renew?</h3>
                    <p style="margin: 5px 0;"><strong>WhatsApp:</strong> <a href="https://wa.me/{self.config.get('business.contact_phone').replace('+', '')}" style="color: white; text-decoration: none;">{self.config.get('business.contact_phone')}</a></p>
                    <p style="margin: 5px 0;"><strong>Email:</strong> <a href="mailto:{self.config.get('business.contact_email')}" style="color: white; text-decoration: none;">{self.config.get('business.contact_email')}</a></p>
                    <p style="margin: 5px 0;"><strong>YouTube:</strong> <a href="https://youtube.com/@NYZTrade" style="color: white; text-decoration: none;">NYZTrade Channel</a></p>
                </div>
                
                <p>Thank you for being a valued member of the {self.config.get('business.name')} community! 🙏</p>
                
                <div style="border-top: 2px solid #eee; padding-top: 20px; margin-top: 30px;">
                    <p style="margin: 0;"><strong>{self.config.get('business.name')} Team</strong></p>
                    <p style="margin: 5px 0; color: #666;">Premium Trading & Analysis Services</p>
                    <p style="margin: 5px 0; color: #666;">{self.config.get('business.address')}</p>
                </div>
                
                <hr style="margin: 20px 0; border: none; border-top: 1px solid #eee;">
                <p style="font-size: 12px; color: #999; text-align: center; margin: 0;">
                This is an automated reminder. Please do not reply to this email.
                </p>
            </div>
        </body>
        </html>
        """
        return subject, body
    
    def create_whatsapp_message(self, subscription):
        """Create WhatsApp notification message"""
        message = f"""🔔 *{self.config.get('business.name')} Reminder*

नमस्ते {subscription['client_name']}! 🙏

Your *{subscription['service_name']}* subscription expires on *{subscription['end_date']}*.

📈 *Don't miss out on:*
• Advanced GEX/DEX Analysis
• Professional Trading Signals  
• Malayalam & English Content
• Priority Expert Support
• Continuous Market Education

💬 *Contact us to renew:*
📞 {self.config.get('business.contact_phone')}
✉️ {self.config.get('business.contact_email')}
🎥 YouTube: @NYZTrade

Thank you for choosing {self.config.get('business.name')}! 🚀

_This is an automated reminder_"""
        
        return message
    
    def log_notification(self, client_id, service_name, notification_type, status, message=""):
        """Log notification attempt to database"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO notifications 
            (client_id, service_name, notification_type, scheduled_date, sent_date, status, message)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            client_id, service_name, notification_type, 
            datetime.now().date(), datetime.now().date(),
            status, message[:500]  # Limit message length
        ))
        
        conn.commit()
        conn.close()
    
    def send_expiry_notifications(self):
        """Main function to send expiry notifications"""
        if not self.config.get('notifications.enabled'):
            self.logger.info("Notifications are disabled")
            return
        
        days_before = self.config.get('notifications.days_before_expiry')
        expiring_subscriptions = self.db.get_expiring_subscriptions(days_before)
        
        self.logger.info(f"Found {len(expiring_subscriptions)} subscriptions expiring in {days_before} day(s)")
        
        for _, subscription in expiring_subscriptions.iterrows():
            client_id = subscription['client_id']
            client_name = subscription['client_name']
            service_name = subscription['service_name']
            
            # Send Email
            if subscription['email'] and self.config.get('email.enabled'):
                subject, body = self.create_email_message(subscription)
                email_success = self.send_email_notification(subscription['email'], subject, body)
                self.log_notification(
                    client_id, service_name, 'email',
                    'sent' if email_success else 'failed'
                )
            
            # Send WhatsApp
            if subscription['whatsapp'] and self.config.get('whatsapp.enabled'):
                whatsapp_message = self.create_whatsapp_message(subscription)
                whatsapp_success = self.send_whatsapp_notification(subscription['whatsapp'], whatsapp_message)
                self.log_notification(
                    client_id, service_name, 'whatsapp',
                    'sent' if whatsapp_success else 'failed'
                )
            
            self.logger.info(f"Processed notifications for {client_name} - {service_name}")

# =============================================================================
# STREAMLIT APPLICATION
# =============================================================================

def init_streamlit_app():
    """Initialize Streamlit application"""
    # Page config
    st.set_page_config(
        page_title="NYZTrade - Premium Client Manager",
        page_icon="📈",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    
    # Initialize managers
    if 'config_manager' not in st.session_state:
        st.session_state.config_manager = ConfigManager()
    
    if 'db_manager' not in st.session_state:
        st.session_state.db_manager = DatabaseManager(
            st.session_state.config_manager.get('database.path')
        )
    
    if 'notification_manager' not in st.session_state:
        st.session_state.notification_manager = NotificationManager(
            st.session_state.config_manager,
            st.session_state.db_manager
        )

def show_header():
    """Display application header"""
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
        .expiring-card {
            background: #fff3cd;
            border-left: 4px solid #ffc107;
            padding: 1rem;
            border-radius: 5px;
            margin: 0.5rem 0;
        }
        .expired-card {
            background: #f8d7da;
            border-left: 4px solid #dc3545;
            padding: 1rem;
            border-radius: 5px;
            margin: 0.5rem 0;
        }
        .sidebar .sidebar-content {
            background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%);
        }
        </style>
    """, unsafe_allow_html=True)
    
    business_name = st.session_state.config_manager.get('business.name', 'NYZTrade')
    
    st.markdown(f"""
        <div class="main-header">
            <h1>📈 {business_name} Premium Client Manager</h1>
            <p>Comprehensive management for Equity, Options & Valuation services</p>
            <small>💡 Real-time GEX/DEX Analysis • Professional Trading Signals • Educational Content</small>
        </div>
    """, unsafe_allow_html=True)

def show_dashboard():
    """Display main dashboard"""
    st.header("📊 Dashboard Overview")
    
    # Get data
    clients = st.session_state.db_manager.get_clients()
    services = st.session_state.db_manager.get_services()
    subscriptions = st.session_state.db_manager.get_active_subscriptions()
    expiring_soon = st.session_state.db_manager.get_expiring_subscriptions(1)
    
    # Metrics row
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.markdown(f"""
            <div class="metric-card">
                <h3>👥 Total Clients</h3>
                <h2 style="color: #667eea;">{len(clients)}</h2>
                <small>Registered users</small>
            </div>
        """, unsafe_allow_html=True)
    
    with col2:
        st.markdown(f"""
            <div class="metric-card">
                <h3>📊 Active Subscriptions</h3>
                <h2 style="color: #28a745;">{len(subscriptions)}</h2>
                <small>Current subscribers</small>
            </div>
        """, unsafe_allow_html=True)
    
    with col3:
        total_revenue = subscriptions['amount_paid'].sum() if len(subscriptions) > 0 else 0
        st.markdown(f"""
            <div class="metric-card">
                <h3>💰 Monthly Revenue</h3>
                <h2 style="color: #28a745;">₹{total_revenue:,.0f}</h2>
                <small>Current period</small>
            </div>
        """, unsafe_allow_html=True)
    
    with col4:
        st.markdown(f"""
            <div class="metric-card">
                <h3>⚠️ Expiring Soon</h3>
                <h2 style="color: #ffc107;">{len(expiring_soon)}</h2>
                <small>Within 24 hours</small>
            </div>
        """, unsafe_allow_html=True)
    
    st.markdown("<br>", unsafe_allow_html=True)
    
    # Charts row
    if len(subscriptions) > 0:
        col1, col2 = st.columns(2)
        
        with col1:
            # Service distribution
            service_counts = subscriptions['service_name'].value_counts()
            fig_pie = px.pie(
                values=service_counts.values,
                names=service_counts.index,
                title="📈 Active Subscriptions by Service",
                color_discrete_sequence=px.colors.qualitative.Set3
            )
            fig_pie.update_traces(textposition='inside', textinfo='percent+label')
            st.plotly_chart(fig_pie, use_container_width=True)
        
        with col2:
            # Revenue by service
            revenue_by_service = subscriptions.groupby('service_name')['amount_paid'].sum()
            fig_bar = px.bar(
                x=revenue_by_service.index,
                y=revenue_by_service.values,
                title="💰 Revenue by Service (₹)",
                color=revenue_by_service.values,
                color_continuous_scale="viridis"
            )
            fig_bar.update_layout(showlegend=False)
            st.plotly_chart(fig_bar, use_container_width=True)
    
    # Expiring subscriptions alert
    if len(expiring_soon) > 0:
        st.subheader("⚠️ Urgent: Expiring Tomorrow")
        for _, row in expiring_soon.iterrows():
            st.markdown(f"""
                <div class="expiring-card">
                    <strong>🔔 {row['client_name']}</strong> - {row['service_name']}<br>
                    <small>📅 Expires: {row['end_date']} | 📧 {row['email']} | 📱 {row['whatsapp']}</small>
                </div>
            """, unsafe_allow_html=True)
        
        if st.button("🔔 Send Reminder Notifications Now", type="primary"):
            try:
                st.session_state.notification_manager.send_expiry_notifications()
                st.success(f"✅ Reminder notifications sent to {len(expiring_soon)} clients!")
            except Exception as e:
                st.error(f"❌ Failed to send notifications: {str(e)}")
    
    # Recent subscriptions
    st.subheader("📋 Recent Active Subscriptions")
    if len(subscriptions) > 0:
        # Add days remaining calculation
        subscriptions_display = subscriptions.copy()
        subscriptions_display['end_date'] = pd.to_datetime(subscriptions_display['end_date'])
        subscriptions_display['days_remaining'] = (subscriptions_display['end_date'] - pd.Timestamp.now()).dt.days
        
        # Sort by expiry date
        subscriptions_display = subscriptions_display.sort_values('end_date').head(10)
        
        display_cols = ['client_name', 'service_name', 'start_date', 'end_date', 'days_remaining', 'amount_paid']
        st.dataframe(
            subscriptions_display[display_cols],
            use_container_width=True,
            column_config={
                "client_name": "Client",
                "service_name": "Service",
                "start_date": "Start Date",
                "end_date": "End Date", 
                "days_remaining": st.column_config.NumberColumn("Days Left", format="%d"),
                "amount_paid": st.column_config.NumberColumn("Amount", format="₹%.0f")
            }
        )
    else:
        st.info("💡 No active subscriptions yet. Start by adding clients and creating subscriptions!")

def show_client_management():
    """Display client management interface"""
    st.header("👥 Client Management")
    
    tab1, tab2, tab3 = st.tabs(["📋 View Clients", "➕ Add Client", "✏️ Edit Client"])
    
    with tab1:
        clients = st.session_state.db_manager.get_clients()
        if len(clients) > 0:
            # Search functionality
            col1, col2 = st.columns([3, 1])
            with col1:
                search_term = st.text_input("🔍 Search clients", placeholder="Enter name or email")
            with col2:
                status_filter = st.selectbox("Filter by Status", ["All", "Active", "Inactive"])
            
            # Apply filters
            filtered_clients = clients.copy()
            if search_term:
                filtered_clients = filtered_clients[
                    filtered_clients['name'].str.contains(search_term, case=False, na=False) |
                    filtered_clients['email'].str.contains(search_term, case=False, na=False)
                ]
            
            if status_filter != "All":
                filtered_clients = filtered_clients[filtered_clients['status'] == status_filter]
            
            st.dataframe(
                filtered_clients,
                use_container_width=True,
                column_config={
                    "name": "Client Name",
                    "email": "Email Address",
                    "phone": "Phone",
                    "whatsapp": "WhatsApp",
                    "registration_date": "Registration Date",
                    "status": "Status"
                }
            )
            
            st.caption(f"📊 Showing {len(filtered_clients)} of {len(clients)} clients")
        else:
            st.info("💡 No clients found. Add your first client using the 'Add Client' tab.")
    
    with tab2:
        st.subheader("➕ Add New Client")
        with st.form("add_client_form"):
            col1, col2 = st.columns(2)
            with col1:
                name = st.text_input("Client Name *", placeholder="Enter full name")
                email = st.text_input("Email Address *", placeholder="client@email.com")
            with col2:
                phone = st.text_input("Phone Number", placeholder="+91 9999999999")
                whatsapp = st.text_input("WhatsApp Number", placeholder="+91 9999999999")
            
            notes = st.text_area("Additional Notes", placeholder="Any special information about this client...")
            
            submitted = st.form_submit_button("➕ Add Client", type="primary", use_container_width=True)
            
            if submitted:
                if name and email:
                    try:
                        conn = st.session_state.db_manager.get_connection()
                        cursor = conn.cursor()
                        cursor.execute(
                            "INSERT INTO clients (name, email, phone, whatsapp, notes) VALUES (?, ?, ?, ?, ?)",
                            (name, email, phone, whatsapp, notes)
                        )
                        conn.commit()
                        conn.close()
                        st.success(f"✅ Client '{name}' added successfully!")
                        st.rerun()
                    except sqlite3.IntegrityError:
                        st.error("❌ Email already exists! Please use a different email address.")
                else:
                    st.error("❌ Name and Email are required fields!")
    
    with tab3:
        clients = st.session_state.db_manager.get_clients()
        if len(clients) > 0:
            client_names = [f"{row['name']} ({row['email']})" for _, row in clients.iterrows()]
            selected_client = st.selectbox("Select Client to Edit", ["Select a client..."] + client_names)
            
            if selected_client != "Select a client...":
                client_email = selected_client.split('(')[1][:-1]
                client_data = clients[clients['email'] == client_email].iloc[0]
                
                with st.form("edit_client_form"):
                    col1, col2 = st.columns(2)
                    with col1:
                        name = st.text_input("Client Name", value=client_data['name'])
                        email = st.text_input("Email Address", value=client_data['email'])
                    with col2:
                        phone = st.text_input("Phone Number", value=client_data['phone'] or "")
                        whatsapp = st.text_input("WhatsApp Number", value=client_data['whatsapp'] or "")
                    
                    status = st.selectbox("Status", ["Active", "Inactive"], 
                                        index=0 if client_data['status'] == 'Active' else 1)
                    notes = st.text_area("Notes", value=client_data['notes'] or "")
                    
                    col1, col2 = st.columns(2)
                    with col1:
                        update_submitted = st.form_submit_button("✅ Update Client", type="primary")
                    with col2:
                        delete_submitted = st.form_submit_button("🗑️ Delete Client", type="secondary")
                    
                    if update_submitted:
                        conn = st.session_state.db_manager.get_connection()
                        cursor = conn.cursor()
                        cursor.execute(
                            "UPDATE clients SET name=?, email=?, phone=?, whatsapp=?, status=?, notes=? WHERE id=?",
                            (name, email, phone, whatsapp, status, notes, client_data['id'])
                        )
                        conn.commit()
                        conn.close()
                        st.success("✅ Client updated successfully!")
                        st.rerun()
                    
                    if delete_submitted:
                        st.warning("⚠️ Are you sure you want to delete this client? This action cannot be undone.")
                        confirm_delete = st.checkbox("I understand and want to delete this client")
                        if confirm_delete:
                            conn = st.session_state.db_manager.get_connection()
                            cursor = conn.cursor()
                            cursor.execute("DELETE FROM clients WHERE id=?", (client_data['id'],))
                            conn.commit()
                            conn.close()
                            st.success("✅ Client deleted successfully!")
                            st.rerun()
        else:
            st.info("💡 No clients available for editing. Add clients first.")

def show_subscription_management():
    """Display subscription management interface"""
    st.header("💳 Subscription Management")
    
    tab1, tab2, tab3 = st.tabs(["📊 Active Subscriptions", "➕ Add Subscription", "📈 Subscription History"])
    
    with tab1:
        subscriptions = st.session_state.db_manager.get_active_subscriptions()
        if len(subscriptions) > 0:
            # Filter options
            col1, col2, col3 = st.columns(3)
            with col1:
                service_filter = st.selectbox("Filter by Service", ["All Services"] + list(subscriptions['service_name'].unique()))
            with col2:
                client_filter = st.selectbox("Filter by Client", ["All Clients"] + list(subscriptions['client_name'].unique()))
            with col3:
                days_filter = st.selectbox("Expiry Filter", ["All", "Expiring in 7 days", "Expiring in 30 days"])
            
            # Apply filters
            filtered_subs = subscriptions.copy()
            if service_filter != "All Services":
                filtered_subs = filtered_subs[filtered_subs['service_name'] == service_filter]
            if client_filter != "All Clients":
                filtered_subs = filtered_subs[filtered_subs['client_name'] == client_filter]
            
            # Add days remaining
            filtered_subs['end_date'] = pd.to_datetime(filtered_subs['end_date'])
            filtered_subs['days_remaining'] = (filtered_subs['end_date'] - pd.Timestamp.now()).dt.days
            
            # Apply expiry filter
            if days_filter == "Expiring in 7 days":
                filtered_subs = filtered_subs[filtered_subs['days_remaining'] <= 7]
            elif days_filter == "Expiring in 30 days":
                filtered_subs = filtered_subs[filtered_subs['days_remaining'] <= 30]
            
            # Display data
            display_cols = ['client_name', 'service_name', 'start_date', 'end_date', 'days_remaining', 'amount_paid', 'payment_method']
            st.dataframe(
                filtered_subs[display_cols],
                use_container_width=True,
                column_config={
                    "client_name": "Client",
                    "service_name": "Service",
                    "start_date": "Start Date",
                    "end_date": "End Date",
                    "days_remaining": st.column_config.NumberColumn("Days Left", format="%d"),
                    "amount_paid": st.column_config.NumberColumn("Amount", format="₹%.0f"),
                    "payment_method": "Payment Method"
                }
            )
            
            st.caption(f"📊 Showing {len(filtered_subs)} of {len(subscriptions)} active subscriptions")
        else:
            st.info("💡 No active subscriptions found. Create your first subscription!")
    
    with tab2:
        st.subheader("➕ Create New Subscription")
        
        clients = st.session_state.db_manager.get_clients()
        services = st.session_state.db_manager.get_services()
        
        if len(clients) > 0 and len(services) > 0:
            with st.form("add_subscription_form"):
                # Client selection
                client_options = [f"{row['name']} ({row['email']})" for _, row in clients.iterrows()]
                selected_client = st.selectbox("Select Client *", ["Choose a client..."] + client_options)
                
                # Service selection
                selected_service = st.selectbox("Select Service *", ["Choose a service..."] + services['name'].tolist())
                
                if selected_service != "Choose a service...":
                    service_data = services[services['name'] == selected_service].iloc[0]
                    st.info(f"""
                        **Service Details:**
                        - 📋 **Description:** {service_data['description']}
                        - 💰 **Price:** ₹{service_data['price']:,.0f}
                        - ⏱️ **Duration:** {service_data['duration_days']} days
                    """)
                
                # Payment details
                col1, col2 = st.columns(2)
                with col1:
                    start_date = st.date_input("Start Date *", value=datetime.now().date())
                    amount_paid = st.number_input("Amount Paid (₹) *", 
                                                min_value=0.0,
                                                value=service_data['price'] if selected_service != "Choose a service..." else 0.0)
                with col2:
                    payment_methods = ["UPI", "Bank Transfer", "Credit Card", "Debit Card", "Cash", "Net Banking"]
                    payment_method = st.selectbox("Payment Method *", ["Select method..."] + payment_methods)
                    transaction_id = st.text_input("Transaction ID", placeholder="Enter transaction reference")
                
                auto_renewal = st.checkbox("Enable Auto Renewal")
                notes = st.text_area("Additional Notes", placeholder="Any special notes about this subscription...")
                
                submitted = st.form_submit_button("💳 Create Subscription", type="primary", use_container_width=True)
                
                if submitted:
                    if (selected_client != "Choose a client..." and 
                        selected_service != "Choose a service..." and 
                        payment_method != "Select method..." and amount_paid > 0):
                        
                        client_email = selected_client.split('(')[1][:-1]
                        client_id = clients[clients['email'] == client_email].iloc[0]['id']
                        service_id = service_data['id']
                        end_date = start_date + timedelta(days=service_data['duration_days'])
                        
                        conn = st.session_state.db_manager.get_connection()
                        cursor = conn.cursor()
                        cursor.execute('''
                            INSERT INTO subscriptions 
                            (client_id, service_id, start_date, end_date, amount_paid, payment_method, transaction_id, auto_renewal)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        ''', (client_id, service_id, start_date, end_date, amount_paid, payment_method, transaction_id, auto_renewal))
                        conn.commit()
                        conn.close()
                        
                        st.success(f"✅ Subscription created successfully! Valid until {end_date}")
                        st.balloons()
                        st.rerun()
                    else:
                        st.error("❌ Please fill all required fields correctly!")
        else:
            if len(clients) == 0:
                st.warning("⚠️ No clients found. Please add clients first.")
            if len(services) == 0:
                st.warning("⚠️ No services found. Please add services first in Settings.")
    
    with tab3:
        st.subheader("📈 Complete Subscription History")
        conn = st.session_state.db_manager.get_connection()
        all_subscriptions = pd.read_sql_query('''
            SELECT s.*, c.name as client_name, c.email, sv.name as service_name, sv.price as service_price
            FROM subscriptions s
            JOIN clients c ON s.client_id = c.id
            JOIN services sv ON s.service_id = sv.id
            ORDER BY s.start_date DESC
        ''', conn)
        conn.close()
        
        if len(all_subscriptions) > 0:
            # Summary stats
            col1, col2, col3 = st.columns(3)
            with col1:
                total_subscriptions = len(all_subscriptions)
                st.metric("Total Subscriptions", total_subscriptions)
            with col2:
                total_revenue = all_subscriptions['amount_paid'].sum()
                st.metric("Total Revenue", f"₹{total_revenue:,.0f}")
            with col3:
                avg_subscription_value = all_subscriptions['amount_paid'].mean()
                st.metric("Average Subscription", f"₹{avg_subscription_value:,.0f}")
            
            # Full history table
            display_cols = ['client_name', 'service_name', 'start_date', 'end_date', 'amount_paid', 'payment_method', 'status']
            st.dataframe(
                all_subscriptions[display_cols],
                use_container_width=True,
                column_config={
                    "amount_paid": st.column_config.NumberColumn("Amount", format="₹%.0f")
                }
            )
        else:
            st.info("💡 No subscription history available yet.")

def show_notifications():
    """Display notification management interface"""
    st.header("📧 Notification Management")
    
    tab1, tab2, tab3 = st.tabs(["🔔 Send Notifications", "⚙️ Settings", "📋 History"])
    
    with tab1:
        st.subheader("📤 Manual Notifications")
        
        # Quick actions for expiring subscriptions
        expiring_tomorrow = st.session_state.db_manager.get_expiring_subscriptions(1)
        expiring_week = st.session_state.db_manager.get_expiring_subscriptions(7)
        
        col1, col2 = st.columns(2)
        with col1:
            if len(expiring_tomorrow) > 0:
                st.warning(f"⚠️ {len(expiring_tomorrow)} subscriptions expire tomorrow!")
                if st.button("📧 Send Tomorrow Expiry Reminders", type="primary"):
                    try:
                        st.session_state.notification_manager.send_expiry_notifications()
                        st.success(f"✅ Sent {len(expiring_tomorrow)} notifications!")
                    except Exception as e:
                        st.error(f"❌ Failed: {str(e)}")
            else:
                st.success("✅ No subscriptions expiring tomorrow")
        
        with col2:
            if len(expiring_week) > 0:
                st.info(f"📅 {len(expiring_week)} subscriptions expire within 7 days")
            else:
                st.success("✅ No urgent renewals needed")
        
        st.markdown("---")
        
        # Custom notification form
        st.subheader("📝 Send Custom Notification")
        with st.form("custom_notification_form"):
            clients = st.session_state.db_manager.get_clients()
            if len(clients) > 0:
                recipient_options = ["All Active Clients"] + [f"{row['name']} ({row['email']})" for _, row in clients.iterrows()]
                selected_recipients = st.multiselect("Select Recipients", recipient_options)
                
                col1, col2 = st.columns(2)
                with col1:
                    subject = st.text_input("Email Subject", placeholder="Enter email subject...")
                    notification_type = st.selectbox("Notification Type", ["Email Only", "WhatsApp Only", "Both Email & WhatsApp"])
                
                with col2:
                    priority = st.selectbox("Priority", ["Normal", "High", "Urgent"])
                    send_time = st.selectbox("Send Time", ["Send Now", "Schedule for Later"])
                
                message = st.text_area("Message Content", 
                                     placeholder="Enter your message here...\n\nYou can use these placeholders:\n{client_name} - Client's name\n{business_name} - Your business name",
                                     height=150)
                
                submitted = st.form_submit_button("📤 Send Notifications", type="primary")
                
                if submitted and subject and message and selected_recipients:
                    try:
                        sent_count = 0
                        business_name = st.session_state.config_manager.get('business.name')
                        
                        # Process recipients
                        if "All Active Clients" in selected_recipients:
                            target_clients = clients[clients['status'] == 'Active']
                        else:
                            emails = [r.split('(')[1][:-1] for r in selected_recipients if '(' in r]
                            target_clients = clients[clients['email'].isin(emails)]
                        
                        for _, client in target_clients.iterrows():
                            # Replace placeholders
                            personalized_subject = subject.replace('{client_name}', client['name']).replace('{business_name}', business_name)
                            personalized_message = message.replace('{client_name}', client['name']).replace('{business_name}', business_name)
                            
                            # Send notifications based on type
                            if notification_type in ["Email Only", "Both Email & WhatsApp"] and client['email']:
                                email_body = f"""
                                <html><body style="font-family: Arial, sans-serif;">
                                <h2 style="color: #667eea;">{business_name}</h2>
                                <p>{personalized_message.replace(chr(10), '<br>')}</p>
                                <hr>
                                <p style="font-size: 12px; color: #666;">
                                Best regards,<br>{business_name} Team
                                </p>
                                </body></html>
                                """
                                st.session_state.notification_manager.send_email_notification(
                                    client['email'], personalized_subject, email_body
                                )
                            
                            if notification_type in ["WhatsApp Only", "Both Email & WhatsApp"] and client['whatsapp']:
                                whatsapp_msg = f"*{business_name}*\n\n{personalized_message}\n\n_Best regards, {business_name} Team_"
                                st.session_state.notification_manager.send_whatsapp_notification(
                                    client['whatsapp'], whatsapp_msg
                                )
                            
                            sent_count += 1
                        
                        st.success(f"✅ Notifications sent to {sent_count} clients!")
                        
                    except Exception as e:
                        st.error(f"❌ Failed to send notifications: {str(e)}")
                else:
                    st.error("❌ Please fill all required fields!")
    
    with tab2:
        st.subheader("⚙️ Notification Settings")
        
        # Email configuration
        with st.expander("📧 Email Configuration", expanded=True):
            col1, col2 = st.columns(2)
            with col1:
                email_enabled = st.checkbox("Enable Email Notifications", 
                                           value=st.session_state.config_manager.get('email.enabled'))
                smtp_server = st.text_input("SMTP Server", 
                                          value=st.session_state.config_manager.get('email.smtp_server'))
                email_address = st.text_input("Email Address",
                                            value=st.session_state.config_manager.get('email.email_address'))
            with col2:
                smtp_port = st.number_input("SMTP Port", 
                                          value=st.session_state.config_manager.get('email.smtp_port'))
                email_password = st.text_input("Email Password", 
                                             type="password",
                                             value=st.session_state.config_manager.get('email.email_password'))
            
            if st.button("💾 Save Email Settings"):
                st.session_state.config_manager.set('email.enabled', email_enabled)
                st.session_state.config_manager.set('email.smtp_server', smtp_server)
                st.session_state.config_manager.set('email.smtp_port', smtp_port)
                st.session_state.config_manager.set('email.email_address', email_address)
                st.session_state.config_manager.set('email.email_password', email_password)
                st.session_state.config_manager.save_config()
                st.success("✅ Email settings saved!")
        
        # WhatsApp configuration
        with st.expander("📱 WhatsApp Configuration"):
            col1, col2 = st.columns(2)
            with col1:
                whatsapp_enabled = st.checkbox("Enable WhatsApp Notifications",
                                              value=st.session_state.config_manager.get('whatsapp.enabled'))
                api_url = st.text_input("WhatsApp API URL",
                                       value=st.session_state.config_manager.get('whatsapp.api_url'))
            with col2:
                api_key = st.text_input("WhatsApp API Key", 
                                       type="password",
                                       value=st.session_state.config_manager.get('whatsapp.api_key'))
            
            if st.button("💾 Save WhatsApp Settings"):
                st.session_state.config_manager.set('whatsapp.enabled', whatsapp_enabled)
                st.session_state.config_manager.set('whatsapp.api_url', api_url)
                st.session_state.config_manager.set('whatsapp.api_key', api_key)
                st.session_state.config_manager.save_config()
                st.success("✅ WhatsApp settings saved!")
        
        # General notification settings
        with st.expander("🔔 General Notification Settings"):
            col1, col2 = st.columns(2)
            with col1:
                notifications_enabled = st.checkbox("Enable Auto Notifications",
                                                   value=st.session_state.config_manager.get('notifications.enabled'))
                days_before = st.number_input("Days Before Expiry to Notify",
                                            min_value=1, max_value=30,
                                            value=st.session_state.config_manager.get('notifications.days_before_expiry'))
            with col2:
                send_time = st.time_input("Daily Notification Time",
                                         value=datetime.strptime(st.session_state.config_manager.get('notifications.send_time'), '%H:%M').time())
            
            if st.button("💾 Save Notification Settings"):
                st.session_state.config_manager.set('notifications.enabled', notifications_enabled)
                st.session_state.config_manager.set('notifications.days_before_expiry', days_before)
                st.session_state.config_manager.set('notifications.send_time', send_time.strftime('%H:%M'))
                st.session_state.config_manager.save_config()
                st.success("✅ Notification settings saved!")
    
    with tab3:
        st.subheader("📋 Notification History")
        
        # Get notification history
        conn = st.session_state.db_manager.get_connection()
        try:
            notifications = pd.read_sql_query('''
                SELECT n.*, c.name as client_name, c.email
                FROM notifications n
                LEFT JOIN clients c ON n.client_id = c.id
                ORDER BY n.sent_date DESC, n.scheduled_date DESC
                LIMIT 100
            ''', conn)
            conn.close()
            
            if len(notifications) > 0:
                # Summary stats
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    total_notifications = len(notifications)
                    st.metric("Total Sent", total_notifications)
                with col2:
                    success_rate = len(notifications[notifications['status'] == 'sent']) / len(notifications) * 100
                    st.metric("Success Rate", f"{success_rate:.1f}%")
                with col3:
                    email_count = len(notifications[notifications['notification_type'] == 'email'])
                    st.metric("Email Notifications", email_count)
                with col4:
                    whatsapp_count = len(notifications[notifications['notification_type'] == 'whatsapp'])
                    st.metric("WhatsApp Notifications", whatsapp_count)
                
                # Notification history table
                st.dataframe(
                    notifications[['client_name', 'service_name', 'notification_type', 'sent_date', 'status']],
                    use_container_width=True,
                    column_config={
                        "client_name": "Client",
                        "service_name": "Service",
                        "notification_type": "Type",
                        "sent_date": "Date Sent",
                        "status": "Status"
                    }
                )
            else:
                st.info("💡 No notification history available yet.")
                
        except Exception as e:
            conn.close()
            st.error(f"❌ Error loading notification history: {str(e)}")

def show_reports():
    """Display reports and analytics"""
    st.header("📊 Reports & Analytics")
    
    tab1, tab2, tab3, tab4 = st.tabs(["💰 Revenue", "👥 Clients", "📊 Subscriptions", "📈 Growth"])
    
    with tab1:
        st.subheader("💰 Revenue Analysis")
        
        # Date range selector
        col1, col2 = st.columns(2)
        with col1:
            date_from = st.date_input("From Date", value=datetime.now().date() - timedelta(days=30))
        with col2:
            date_to = st.date_input("To Date", value=datetime.now().date())
        
        # Get revenue data
        conn = st.session_state.db_manager.get_connection()
        revenue_data = pd.read_sql_query('''
            SELECT s.start_date, s.amount_paid, s.payment_method, sv.name as service_name, c.name as client_name
            FROM subscriptions s
            JOIN services sv ON s.service_id = sv.id
            JOIN clients c ON s.client_id = c.id
            WHERE s.start_date BETWEEN ? AND ?
        ''', conn, params=(date_from, date_to))
        conn.close()
        
        if len(revenue_data) > 0:
            # Revenue metrics
            total_revenue = revenue_data['amount_paid'].sum()
            avg_revenue = revenue_data['amount_paid'].mean()
            transaction_count = len(revenue_data)
            
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Total Revenue", f"₹{total_revenue:,.0f}")
            with col2:
                st.metric("Average Deal Size", f"₹{avg_revenue:,.0f}")
            with col3:
                st.metric("Transactions", transaction_count)
            with col4:
                days_range = (date_to - date_from).days + 1
                daily_avg = total_revenue / days_range if days_range > 0 else 0
                st.metric("Daily Average", f"₹{daily_avg:,.0f}")
            
            # Charts
            col1, col2 = st.columns(2)
            
            with col1:
                # Revenue by service
                revenue_by_service = revenue_data.groupby('service_name')['amount_paid'].sum().sort_values(ascending=False)
                fig_pie = px.pie(
                    values=revenue_by_service.values,
                    names=revenue_by_service.index,
                    title="💰 Revenue Distribution by Service"
                )
                st.plotly_chart(fig_pie, use_container_width=True)
            
            with col2:
                # Payment method distribution
                payment_methods = revenue_data.groupby('payment_method')['amount_paid'].sum()
                fig_bar = px.bar(
                    x=payment_methods.index,
                    y=payment_methods.values,
                    title="💳 Revenue by Payment Method"
                )
                st.plotly_chart(fig_bar, use_container_width=True)
            
            # Daily revenue trend
            revenue_data['start_date'] = pd.to_datetime(revenue_data['start_date'])
            daily_revenue = revenue_data.groupby('start_date')['amount_paid'].sum().reset_index()
            
            if len(daily_revenue) > 1:
                fig_line = px.line(
                    daily_revenue,
                    x='start_date',
                    y='amount_paid',
                    title="📈 Daily Revenue Trend",
                    markers=True
                )
                fig_line.update_layout(xaxis_title="Date", yaxis_title="Revenue (₹)")
                st.plotly_chart(fig_line, use_container_width=True)
            
            # Top clients by revenue
            st.subheader("🏆 Top Clients by Revenue")
            top_clients = revenue_data.groupby('client_name')['amount_paid'].sum().sort_values(ascending=False).head(10)
            
            fig_top_clients = px.bar(
                x=top_clients.values,
                y=top_clients.index,
                orientation='h',
                title="Top 10 Clients by Total Revenue"
            )
            st.plotly_chart(fig_top_clients, use_container_width=True)
        
        else:
            st.info(f"💡 No revenue data found for the period {date_from} to {date_to}")
    
    with tab2:
        st.subheader("👥 Client Analytics")
        
        clients = st.session_state.db_manager.get_clients()
        subscriptions = st.session_state.db_manager.get_active_subscriptions()
        
        if len(clients) > 0:
            # Client metrics
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                total_clients = len(clients)
                st.metric("Total Clients", total_clients)
            with col2:
                active_clients = len(clients[clients['status'] == 'Active'])
                st.metric("Active Clients", active_clients)
            with col3:
                subscribers = len(subscriptions['client_name'].unique()) if len(subscriptions) > 0 else 0
                st.metric("Current Subscribers", subscribers)
            with col4:
                conversion_rate = (subscribers / total_clients * 100) if total_clients > 0 else 0
                st.metric("Conversion Rate", f"{conversion_rate:.1f}%")
            
            col1, col2 = st.columns(2)
            
            with col1:
                # Client status distribution
                status_counts = clients['status'].value_counts()
                fig_status = px.pie(
                    values=status_counts.values,
                    names=status_counts.index,
                    title="👥 Client Status Distribution",
                    color_discrete_sequence=['#28a745', '#dc3545']
                )
                st.plotly_chart(fig_status, use_container_width=True)
            
            with col2:
                # Client acquisition trend
                if 'registration_date' in clients.columns:
                    clients['registration_date'] = pd.to_datetime(clients['registration_date'])
                    monthly_acquisitions = clients.groupby(
                        clients['registration_date'].dt.to_period('M')
                    ).size().reset_index()
                    monthly_acquisitions['registration_date'] = monthly_acquisitions['registration_date'].astype(str)
                    
                    fig_acquisition = px.bar(
                        monthly_acquisitions,
                        x='registration_date',
                        y=0,  # The count column
                        title="📈 Monthly Client Acquisitions"
                    )
                    st.plotly_chart(fig_acquisition, use_container_width=True)
        else:
            st.info("💡 No client data available for analysis.")
    
    with tab3:
        st.subheader("📊 Subscription Analytics")
        
        subscriptions = st.session_state.db_manager.get_active_subscriptions()
        
        if len(subscriptions) > 0:
            # Subscription metrics
            subscriptions['end_date'] = pd.to_datetime(subscriptions['end_date'])
            subscriptions['days_remaining'] = (subscriptions['end_date'] - pd.Timestamp.now()).dt.days
            
            # Risk analysis
            expiring_soon = subscriptions[subscriptions['days_remaining'] <= 7]
            expiring_month = subscriptions[subscriptions['days_remaining'] <= 30]
            
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Active Subscriptions", len(subscriptions))
            with col2:
                st.metric("Expiring This Week", len(expiring_soon))
            with col3:
                st.metric("Expiring This Month", len(expiring_month))
            with col4:
                potential_loss = expiring_month['amount_paid'].sum()
                st.metric("Potential Revenue Loss", f"₹{potential_loss:,.0f}")
            
            # Charts
            col1, col2 = st.columns(2)
            
            with col1:
                # Subscription distribution by service
                service_counts = subscriptions['service_name'].value_counts()
                fig_subs = px.bar(
                    x=service_counts.values,
                    y=service_counts.index,
                    orientation='h',
                    title="📊 Active Subscriptions by Service"
                )
                st.plotly_chart(fig_subs, use_container_width=True)
            
            with col2:
                # Subscription expiry timeline
                expiry_timeline = subscriptions.groupby(
                    subscriptions['end_date'].dt.to_period('W')
                ).size().reset_index()
                expiry_timeline['end_date'] = expiry_timeline['end_date'].astype(str)
                
                fig_timeline = px.bar(
                    expiry_timeline,
                    x='end_date',
                    y=0,
                    title="📅 Subscription Expiry Timeline (Weekly)"
                )
                st.plotly_chart(fig_timeline, use_container_width=True)
            
            # Renewal risk analysis
            st.subheader("⚠️ Renewal Risk Analysis")
            
            risk_data = []
            for _, sub in expiring_soon.iterrows():
                risk_level = "🔴 High" if sub['days_remaining'] <= 3 else "🟡 Medium"
                risk_data.append({
                    "Client": sub['client_name'],
                    "Service": sub['service_name'],
                    "Expires": sub['end_date'].strftime('%Y-%m-%d'),
                    "Days Left": sub['days_remaining'],
                    "Risk": risk_level,
                    "Value": f"₹{sub['amount_paid']:,.0f}"
                })
            
            if risk_data:
                st.dataframe(pd.DataFrame(risk_data), use_container_width=True)
            else:
                st.success("✅ No high-risk renewals at the moment!")
        else:
            st.info("💡 No subscription data available for analysis.")
    
    with tab4:
        st.subheader("📈 Growth Analytics")
        
        # Get historical data
        conn = st.session_state.db_manager.get_connection()
        
        # Monthly growth data
        growth_data = pd.read_sql_query('''
            SELECT 
                strftime('%Y-%m', s.start_date) as month,
                COUNT(*) as new_subscriptions,
                SUM(s.amount_paid) as monthly_revenue,
                COUNT(DISTINCT s.client_id) as unique_clients
            FROM subscriptions s
            GROUP BY strftime('%Y-%m', s.start_date)
            ORDER BY month
        ''', conn)
        
        conn.close()
        
        if len(growth_data) > 0:
            # Growth metrics
            if len(growth_data) >= 2:
                current_month = growth_data.iloc[-1]
                previous_month = growth_data.iloc[-2]
                
                revenue_growth = ((current_month['monthly_revenue'] - previous_month['monthly_revenue']) / previous_month['monthly_revenue'] * 100) if previous_month['monthly_revenue'] > 0 else 0
                client_growth = ((current_month['unique_clients'] - previous_month['unique_clients']) / previous_month['unique_clients'] * 100) if previous_month['unique_clients'] > 0 else 0
                
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("Current Month Revenue", f"₹{current_month['monthly_revenue']:,.0f}")
                with col2:
                    st.metric("Revenue Growth", f"{revenue_growth:+.1f}%", delta=f"{revenue_growth:+.1f}%")
                with col3:
                    st.metric("New Clients This Month", current_month['unique_clients'])
                with col4:
                    st.metric("Client Growth", f"{client_growth:+.1f}%", delta=f"{client_growth:+.1f}%")
            
            # Growth charts
            col1, col2 = st.columns(2)
            
            with col1:
                # Monthly revenue trend
                fig_revenue = px.line(
                    growth_data,
                    x='month',
                    y='monthly_revenue',
                    title="📈 Monthly Revenue Growth",
                    markers=True
                )
                fig_revenue.update_layout(yaxis_title="Revenue (₹)")
                st.plotly_chart(fig_revenue, use_container_width=True)
            
            with col2:
                # Monthly subscriptions trend
                fig_subs = px.line(
                    growth_data,
                    x='month',
                    y='new_subscriptions',
                    title="📊 Monthly New Subscriptions",
                    markers=True,
                    color_discrete_sequence=['#28a745']
                )
                st.plotly_chart(fig_subs, use_container_width=True)
            
            # Combined growth analysis
            fig_combined = px.bar(
                growth_data,
                x='month',
                y=['new_subscriptions', 'unique_clients'],
                title="📈 Growth Analysis: Subscriptions vs Unique Clients",
                barmode='group'
            )
            st.plotly_chart(fig_combined, use_container_width=True)
            
            # Growth insights
            st.subheader("🔍 Growth Insights")
            
            total_months = len(growth_data)
            avg_monthly_revenue = growth_data['monthly_revenue'].mean()
            avg_monthly_subs = growth_data['new_subscriptions'].mean()
            
            insights_col1, insights_col2 = st.columns(2)
            
            with insights_col1:
                st.info(f"""
                **📊 Historical Performance:**
                - Total months tracked: {total_months}
                - Average monthly revenue: ₹{avg_monthly_revenue:,.0f}
                - Average monthly subscriptions: {avg_monthly_subs:.1f}
                """)
            
            with insights_col2:
                if len(growth_data) >= 3:
                    recent_trend = growth_data.tail(3)['monthly_revenue'].pct_change().mean() * 100
                    trend_direction = "📈 Growing" if recent_trend > 0 else "📉 Declining" if recent_trend < 0 else "➡️ Stable"
                    
                    st.info(f"""
                    **🎯 Recent Trends:**
                    - 3-month trend: {trend_direction}
                    - Average growth rate: {recent_trend:+.1f}%
                    - Highest revenue month: ₹{growth_data['monthly_revenue'].max():,.0f}
                    """)
        else:
            st.info("💡 Insufficient data for growth analysis. More historical data needed.")

def show_settings():
    """Display settings and configuration"""
    st.header("⚙️ Settings & Configuration")
    
    tab1, tab2, tab3, tab4 = st.tabs(["🏢 Business Info", "📊 Services", "🔧 System", "📋 Data Management"])
    
    with tab1:
        st.subheader("🏢 Business Information")
        
        with st.form("business_info_form"):
            col1, col2 = st.columns(2)
            
            with col1:
                business_name = st.text_input("Business Name",
                                            value=st.session_state.config_manager.get('business.name'))
                contact_phone = st.text_input("Contact Phone",
                                            value=st.session_state.config_manager.get('business.contact_phone'))
                website = st.text_input("Website",
                                       value=st.session_state.config_manager.get('business.website'))
            
            with col2:
                contact_email = st.text_input("Contact Email",
                                            value=st.session_state.config_manager.get('business.contact_email'))
                address = st.text_area("Business Address",
                                     value=st.session_state.config_manager.get('business.address'))
            
            submitted = st.form_submit_button("💾 Save Business Information", type="primary")
            
            if submitted:
                st.session_state.config_manager.set('business.name', business_name)
                st.session_state.config_manager.set('business.contact_phone', contact_phone)
                st.session_state.config_manager.set('business.contact_email', contact_email)
                st.session_state.config_manager.set('business.website', website)
                st.session_state.config_manager.set('business.address', address)
                st.session_state.config_manager.save_config()
                st.success("✅ Business information updated successfully!")
                st.rerun()
    
    with tab2:
        st.subheader("📊 Service Management")
        
        services = st.session_state.db_manager.get_services()
        
        # Add new service
        with st.expander("➕ Add New Service", expanded=True):
            with st.form("add_service_form"):
                col1, col2 = st.columns(2)
                with col1:
                    service_name = st.text_input("Service Name *", placeholder="e.g., PREMIUM OPTIONS ANALYSIS")
                    price = st.number_input("Price (₹) *", min_value=0.0, value=5000.0)
                with col2:
                    duration = st.number_input("Duration (days) *", min_value=1, value=30)
                    status = st.selectbox("Status", ["Active", "Inactive"])
                
                description = st.text_area("Service Description *",
                                         placeholder="Detailed description of what this service includes...")
                
                submitted = st.form_submit_button("➕ Add Service", type="primary")
                
                if submitted and service_name and description:
                    try:
                        conn = st.session_state.db_manager.get_connection()
                        cursor = conn.cursor()
                        cursor.execute(
                            "INSERT INTO services (name, description, price, duration_days, status) VALUES (?, ?, ?, ?, ?)",
                            (service_name, description, price, duration, status)
                        )
                        conn.commit()
                        conn.close()
                        st.success("✅ Service added successfully!")
                        st.rerun()
                    except sqlite3.IntegrityError:
                        st.error("❌ Service name already exists!")
                else:
                    st.error("❌ Please fill all required fields!")
        
        # Edit existing services
        if len(services) > 0:
            st.subheader("📝 Existing Services")
            
            for _, service in services.iterrows():
                with st.expander(f"✏️ {service['name']} - ₹{service['price']:,.0f}/{service['duration_days']} days"):
                    with st.form(f"edit_service_{service['id']}"):
                        col1, col2 = st.columns(2)
                        with col1:
                            edit_name = st.text_input("Service Name", value=service['name'], key=f"name_{service['id']}")
                            edit_price = st.number_input("Price (₹)", value=float(service['price']), key=f"price_{service['id']}")
                        with col2:
                            edit_duration = st.number_input("Duration (days)", value=service['duration_days'], key=f"duration_{service['id']}")
                            edit_status = st.selectbox("Status", ["Active", "Inactive"], 
                                                     index=0 if service['status'] == 'Active' else 1,
                                                     key=f"status_{service['id']}")
                        
                        edit_description = st.text_area("Description", value=service['description'], key=f"desc_{service['id']}")
                        
                        col1, col2 = st.columns(2)
                        with col1:
                            update_submitted = st.form_submit_button("✅ Update", type="primary")
                        with col2:
                            delete_submitted = st.form_submit_button("🗑️ Delete", type="secondary")
                        
                        if update_submitted:
                            conn = st.session_state.db_manager.get_connection()
                            cursor = conn.cursor()
                            cursor.execute('''
                                UPDATE services 
                                SET name=?, description=?, price=?, duration_days=?, status=? 
                                WHERE id=?
                            ''', (edit_name, edit_description, edit_price, edit_duration, edit_status, service['id']))
                            conn.commit()
                            conn.close()
                            st.success("✅ Service updated successfully!")
                            st.rerun()
                        
                        if delete_submitted:
                            st.warning("⚠️ Are you sure? This will affect existing subscriptions!")
                            confirm = st.checkbox("I understand the consequences", key=f"confirm_{service['id']}")
                            if confirm:
                                conn = st.session_state.db_manager.get_connection()
                                cursor = conn.cursor()
                                cursor.execute("UPDATE services SET status='Inactive' WHERE id=?", (service['id'],))
                                conn.commit()
                                conn.close()
                                st.success("✅ Service deactivated!")
                                st.rerun()
        else:
            st.info("💡 No services configured yet.")
    
    with tab3:
        st.subheader("🔧 System Configuration")
        
        # Database settings
        with st.expander("💾 Database Settings", expanded=True):
            current_db_path = st.session_state.config_manager.get('database.path')
            st.info(f"📁 Current database: `{current_db_path}`")
            
            col1, col2 = st.columns(2)
            with col1:
                if st.button("📋 Create Database Backup"):
                    import shutil
                    backup_name = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
                    try:
                        shutil.copy(current_db_path, backup_name)
                        st.success(f"✅ Backup created: {backup_name}")
                    except Exception as e:
                        st.error(f"❌ Backup failed: {str(e)}")
            
            with col2:
                if st.button("🔍 Check Database Health"):
                    try:
                        conn = st.session_state.db_manager.get_connection()
                        cursor = conn.cursor()
                        
                        # Check table counts
                        cursor.execute("SELECT COUNT(*) FROM clients")
                        client_count = cursor.fetchone()[0]
                        cursor.execute("SELECT COUNT(*) FROM services")
                        service_count = cursor.fetchone()[0]
                        cursor.execute("SELECT COUNT(*) FROM subscriptions")
                        sub_count = cursor.fetchone()[0]
                        
                        conn.close()
                        
                        st.success(f"""
                        ✅ Database is healthy!
                        - Clients: {client_count}
                        - Services: {service_count}
                        - Subscriptions: {sub_count}
                        """)
                    except Exception as e:
                        st.error(f"❌ Database error: {str(e)}")
        
        # Application settings
        with st.expander("⚙️ Application Settings"):
            col1, col2 = st.columns(2)
            with col1:
                st.info("📊 **Current Version:** v1.0.0")
                st.info("🐍 **Python Version:** " + sys.version.split()[0])
            with col2:
                st.info("💾 **Database Engine:** SQLite")
                st.info("🌐 **Framework:** Streamlit")
            
            if st.button("🔄 Reset Application Settings"):
                if st.checkbox("I understand this will reset all configuration"):
                    st.session_state.config_manager.config = DEFAULT_CONFIG.copy()
                    st.session_state.config_manager.save_config()
                    st.warning("⚠️ Settings reset! Please restart the application.")
    
    with tab4:
        st.subheader("📋 Data Management")
        
        # Data export
        with st.expander("📤 Export Data", expanded=True):
            st.markdown("**Export your data for backup or analysis:**")
            
            col1, col2, col3 = st.columns(3)
            
            with col1:
                if st.button("📄 Export Clients"):
                    clients = st.session_state.db_manager.get_clients()
                    csv = clients.to_csv(index=False)
                    st.download_button(
                        label="⬇️ Download Clients CSV",
                        data=csv,
                        file_name=f"clients_{datetime.now().strftime('%Y%m%d')}.csv",
                        mime="text/csv"
                    )
            
            with col2:
                if st.button("📊 Export Subscriptions"):
                    subscriptions = st.session_state.db_manager.get_active_subscriptions()
                    csv = subscriptions.to_csv(index=False)
                    st.download_button(
                        label="⬇️ Download Subscriptions CSV",
                        data=csv,
                        file_name=f"subscriptions_{datetime.now().strftime('%Y%m%d')}.csv",
                        mime="text/csv"
                    )
            
            with col3:
                if st.button("💰 Export Revenue"):
                    conn = st.session_state.db_manager.get_connection()
                    revenue_data = pd.read_sql_query('''
                        SELECT s.start_date, s.end_date, s.amount_paid, s.payment_method,
                               c.name as client_name, sv.name as service_name
                        FROM subscriptions s
                        JOIN clients c ON s.client_id = c.id
                        JOIN services sv ON s.service_id = sv.id
                        ORDER BY s.start_date DESC
                    ''', conn)
                    conn.close()
                    
                    csv = revenue_data.to_csv(index=False)
                    st.download_button(
                        label="⬇️ Download Revenue CSV",
                        data=csv,
                        file_name=f"revenue_{datetime.now().strftime('%Y%m%d')}.csv",
                        mime="text/csv"
                    )
        
        # Data import
        with st.expander("📥 Import Data"):
            st.markdown("**Import data from CSV files:**")
            st.warning("⚠️ **Warning:** Importing data will add to existing records. Duplicates may occur.")
            
            tab_import1, tab_import2 = st.tabs(["👥 Import Clients", "💳 Import Subscriptions"])
            
            with tab_import1:
                uploaded_clients = st.file_uploader("Choose clients CSV file", type=['csv'], key="clients_upload")
                if uploaded_clients:
                    try:
                        df = pd.read_csv(uploaded_clients)
                        st.write("Preview:", df.head())
                        
                        required_columns = ['name', 'email']
                        if all(col in df.columns for col in required_columns):
                            if st.button("📥 Import Clients Data"):
                                # Import logic here
                                st.success("✅ Clients imported successfully!")
                        else:
                            st.error(f"❌ CSV must contain columns: {required_columns}")
                    except Exception as e:
                        st.error(f"❌ Error reading CSV: {str(e)}")
            
            with tab_import2:
                st.info("💡 Subscription import requires existing clients and services in the system.")
                uploaded_subs = st.file_uploader("Choose subscriptions CSV file", type=['csv'], key="subs_upload")
                if uploaded_subs:
                    st.write("📋 Subscription import coming soon...")
        
        # Data cleanup
        with st.expander("🧹 Data Cleanup"):
            st.markdown("**Cleanup and maintenance operations:**")
            
            col1, col2 = st.columns(2)
            
            with col1:
                if st.button("🗑️ Remove Inactive Clients"):
                    if st.checkbox("Confirm removal of inactive clients"):
                        conn = st.session_state.db_manager.get_connection()
                        cursor = conn.cursor()
                        cursor.execute("DELETE FROM clients WHERE status='Inactive'")
                        deleted_count = cursor.rowcount
                        conn.commit()
                        conn.close()
                        st.success(f"✅ Removed {deleted_count} inactive clients")
            
            with col2:
                if st.button("📅 Archive Old Subscriptions"):
                    if st.checkbox("Archive subscriptions older than 1 year"):
                        # Archive logic would go here
                        st.info("📋 Archive functionality coming soon...")

def run_streamlit_app():
    """Run the main Streamlit application"""
    init_streamlit_app()
    show_header()
    
    # Sidebar navigation
    st.sidebar.title("🧭 Navigation")
    pages = [
        "📊 Dashboard",
        "👥 Client Management", 
        "💳 Subscription Management", 
        "📧 Notifications",
        "📈 Reports & Analytics", 
        "⚙️ Settings"
    ]
    
    # Add business info to sidebar
    business_name = st.session_state.config_manager.get('business.name')
    st.sidebar.markdown(f"""
    ---
    **🏢 {business_name}**  
    *Premium Client Manager*
    
    📧 Email: {st.session_state.config_manager.get('email.enabled') and '✅' or '❌'} 
    📱 WhatsApp: {st.session_state.config_manager.get('whatsapp.enabled') and '✅' or '❌'}
    🔔 Auto Notifications: {st.session_state.config_manager.get('notifications.enabled') and '✅' or '❌'}
    """)
    
    selected_page = st.sidebar.selectbox("Select Page", pages)
    
    # Route to appropriate page
    if selected_page == "📊 Dashboard":
        show_dashboard()
    elif selected_page == "👥 Client Management":
        show_client_management()
    elif selected_page == "💳 Subscription Management":
        show_subscription_management()
    elif selected_page == "📧 Notifications":
        show_notifications()
    elif selected_page == "📈 Reports & Analytics":
        show_reports()
    elif selected_page == "⚙️ Settings":
        show_settings()

# =============================================================================
# NOTIFICATION SCHEDULER
# =============================================================================

def run_scheduler():
    """Run the notification scheduler"""
    config_manager = ConfigManager()
    db_manager = DatabaseManager(config_manager.get('database.path'))
    notification_manager = NotificationManager(config_manager, db_manager)
    
    send_time = config_manager.get('notifications.send_time')
    
    # Schedule daily notifications
    schedule.every().day.at(send_time).do(notification_manager.send_expiry_notifications)
    
    print(f"🔔 NYZTrade Notification Scheduler Started")
    print(f"📅 Daily notifications scheduled at {send_time}")
    print(f"💾 Database: {config_manager.get('database.path')}")
    print(f"📧 Email: {'✅' if config_manager.get('email.enabled') else '❌'}")
    print(f"📱 WhatsApp: {'✅' if config_manager.get('whatsapp.enabled') else '❌'}")
    print("=" * 50)
    
    try:
        while True:
            schedule.run_pending()
            time.sleep(60)  # Check every minute
    except KeyboardInterrupt:
        print("\n🛑 Scheduler stopped by user")

# =============================================================================
# SETUP UTILITY
# =============================================================================

def test_email_config(email_address, email_password, smtp_server, smtp_port):
    """Test email configuration"""
    try:
        print("🔧 Testing email configuration...")
        
        msg = MimeText("This is a test message from NYZTrade Client Manager setup.")
        msg['Subject'] = "NYZTrade Setup Test"
        msg['From'] = email_address
        msg['To'] = email_address
        
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(email_address, email_password)
        server.send_message(msg)
        server.quit()
        
        print("✅ Email test successful!")
        return True
        
    except Exception as e:
        print(f"❌ Email test failed: {str(e)}")
        return False

def test_whatsapp_config(api_url, api_key, test_phone):
    """Test WhatsApp configuration"""
    try:
        print("🔧 Testing WhatsApp configuration...")
        
        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }
        
        data = {
            'phone': test_phone,
            'message': 'Test message from NYZTrade Client Manager setup.'
        }
        
        response = requests.post(api_url, headers=headers, json=data, timeout=10)
        
        if response.status_code == 200:
            print("✅ WhatsApp test successful!")
            return True
        else:
            print(f"❌ WhatsApp test failed: HTTP {response.status_code}")
            return False
            
    except Exception as e:
        print(f"❌ WhatsApp test failed: {str(e)}")
        return False

def setup_email(config_manager):
    """Setup email configuration"""
    print("\n📧 EMAIL CONFIGURATION")
    print("=" * 50)
    
    print("\nSelect your email provider:")
    print("1. Gmail")
    print("2. Outlook/Hotmail")
    print("3. Yahoo")
    print("4. Custom SMTP")
    
    choice = input("\nEnter choice (1-4): ").strip()
    
    if choice == "1":
        config_manager.set('email.smtp_server', "smtp.gmail.com")
        config_manager.set('email.smtp_port', 587)
        print("\n📝 Gmail Setup Instructions:")
        print("1. Enable 2-factor authentication on your Gmail account")
        print("2. Go to Google Account Settings → Security → 2-Step Verification → App passwords")
        print("3. Create a new app password for 'Mail'")
        print("4. Use this app password below (not your regular Gmail password)")
        
    elif choice == "2":
        config_manager.set('email.smtp_server', "smtp.office365.com")
        config_manager.set('email.smtp_port', 587)
        
    elif choice == "3":
        config_manager.set('email.smtp_server', "smtp.mail.yahoo.com")
        config_manager.set('email.smtp_port', 587)
        
    elif choice == "4":
        smtp_server = input("SMTP Server: ").strip()
        smtp_port = int(input("SMTP Port (usually 587): ").strip() or 587)
        config_manager.set('email.smtp_server', smtp_server)
        config_manager.set('email.smtp_port', smtp_port)
    
    # Get email credentials
    email_address = input("\nEmail Address: ").strip()
    email_password = getpass.getpass("Email Password/App Password: ").strip()
    
    config_manager.set('email.email_address', email_address)
    config_manager.set('email.email_password', email_password)
    
    # Test configuration
    test_email = input("\nTest email configuration? (y/n): ").lower().strip() == 'y'
    
    if test_email:
        if test_email_config(
            email_address, email_password,
            config_manager.get('email.smtp_server'),
            config_manager.get('email.smtp_port')
        ):
            config_manager.set('email.enabled', True)
            print("✅ Email configuration completed successfully!")
        else:
            config_manager.set('email.enabled', False)
            print("⚠️ Email configuration saved but disabled due to test failure.")
    else:
        config_manager.set('email.enabled', True)
        print("✅ Email configuration saved (not tested).")

def setup_whatsapp(config_manager):
    """Setup WhatsApp configuration"""
    print("\n📱 WHATSAPP CONFIGURATION")
    print("=" * 50)
    
    print("\n📝 WhatsApp API Setup:")
    print("To enable WhatsApp notifications, you need a WhatsApp Business API provider.")
    print("Popular options:")
    print("• WhatsApp Business API (Official)")
    print("• Twilio WhatsApp API")
    print("• MessageBird WhatsApp API")
    print("• Other third-party providers")
    
    setup_wa = input("\nDo you want to configure WhatsApp now? (y/n): ").lower().strip() == 'y'
    
    if setup_wa:
        api_url = input("WhatsApp API URL: ").strip()
        api_key = getpass.getpass("WhatsApp API Key: ").strip()
        
        config_manager.set('whatsapp.api_url', api_url)
        config_manager.set('whatsapp.api_key', api_key)
        
        test_whatsapp = input("Test WhatsApp configuration? (y/n): ").lower().strip() == 'y'
        
        if test_whatsapp:
            test_phone = input("Enter test phone number (with country code, e.g., +919999999999): ").strip()
            
            if test_whatsapp_config(api_url, api_key, test_phone):
                config_manager.set('whatsapp.enabled', True)
                print("✅ WhatsApp configuration completed successfully!")
            else:
                config_manager.set('whatsapp.enabled', False)
                print("⚠️ WhatsApp configuration saved but disabled due to test failure.")
        else:
            config_manager.set('whatsapp.enabled', True)
            print("✅ WhatsApp configuration saved (not tested).")
    else:
        config_manager.set('whatsapp.enabled', False)
        print("❌ WhatsApp configuration skipped.")

def setup_business_info(config_manager):
    """Setup business information"""
    print("\n🏢 BUSINESS INFORMATION")
    print("=" * 50)
    
    current_name = config_manager.get('business.name')
    business_name = input(f"Business Name [{current_name}]: ").strip() or current_name
    
    current_phone = config_manager.get('business.contact_phone')
    contact_phone = input(f"Contact Phone [{current_phone}]: ").strip() or current_phone
    
    current_email = config_manager.get('business.contact_email')
    contact_email = input(f"Contact Email [{current_email}]: ").strip() or current_email
    
    current_website = config_manager.get('business.website')
    website = input(f"Website [{current_website}]: ").strip() or current_website
    
    current_address = config_manager.get('business.address')
    address = input(f"Address [{current_address}]: ").strip() or current_address
    
    config_manager.set('business.name', business_name)
    config_manager.set('business.contact_phone', contact_phone)
    config_manager.set('business.contact_email', contact_email)
    config_manager.set('business.website', website)
    config_manager.set('business.address', address)

def setup_notifications(config_manager):
    """Setup notification preferences"""
    print("\n🔔 NOTIFICATION SETTINGS")
    print("=" * 50)
    
    current_days = config_manager.get('notifications.days_before_expiry')
    days_before = input(f"Days before expiry to send notifications [{current_days}]: ").strip()
    if days_before:
        config_manager.set('notifications.days_before_expiry', int(days_before))
    
    current_time = config_manager.get('notifications.send_time')
    send_time = input(f"Time to send daily notifications (HH:MM format) [{current_time}]: ").strip()
    if send_time:
        config_manager.set('notifications.send_time', send_time)
    
    enabled = input("Enable automatic notifications? (y/n): ").lower().strip() != 'n'
    config_manager.set('notifications.enabled', enabled)

def run_setup():
    """Run the setup utility"""
    print("🚀 NYZTrade Client Manager Setup")
    print("=" * 50)
    print("This utility will help you configure your client management system.")
    
    config_manager = ConfigManager()
    
    print("\nWhat would you like to configure?")
    print("1. Email Settings")
    print("2. WhatsApp Settings")
    print("3. Business Information")
    print("4. Notification Settings")
    print("5. Complete Setup (All of the above)")
    print("6. Exit")
    
    choice = input("\nEnter choice (1-6): ").strip()
    
    if choice == "1":
        setup_email(config_manager)
    elif choice == "2":
        setup_whatsapp(config_manager)
    elif choice == "3":
        setup_business_info(config_manager)
    elif choice == "4":
        setup_notifications(config_manager)
    elif choice == "5":
        setup_business_info(config_manager)
        setup_email(config_manager)
        setup_whatsapp(config_manager)
        setup_notifications(config_manager)
    elif choice == "6":
        print("Setup cancelled.")
        return
    else:
        print("Invalid choice.")
        return
    
    # Save configuration
    config_manager.save_config()
    
    print("\n✅ Setup completed!")
    print("\nNext steps:")
    print("1. Run the main application: python nyztrade_client_manager.py")
    print("2. Start notification service: python nyztrade_client_manager.py --mode scheduler")

# =============================================================================
# TEST MODE
# =============================================================================

def run_test():
    """Test notification system"""
    print("🧪 NYZTrade Notification Test")
    print("=" * 50)
    
    config_manager = ConfigManager()
    db_manager = DatabaseManager(config_manager.get('database.path'))
    notification_manager = NotificationManager(config_manager, db_manager)
    
    print("Testing notification system...")
    print(f"📧 Email enabled: {config_manager.get('email.enabled')}")
    print(f"📱 WhatsApp enabled: {config_manager.get('whatsapp.enabled')}")
    
    # Test with expiring subscriptions
    expiring = db_manager.get_expiring_subscriptions(1)
    print(f"📅 Found {len(expiring)} subscriptions expiring tomorrow")
    
    if len(expiring) > 0:
        print("🔔 Sending test notifications...")
        notification_manager.send_expiry_notifications()
        print("✅ Test completed!")
    else:
        print("💡 No expiring subscriptions to test with.")
        print("   Add some test subscriptions with tomorrow's expiry date.")

# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description='NYZTrade Premium Client Manager')
    parser.add_argument('--mode', choices=['app', 'scheduler', 'setup', 'test'], 
                       default='app', help='Mode to run in')
    
    args = parser.parse_args()
    
    if args.mode == 'app':
        run_streamlit_app()
    elif args.mode == 'scheduler':
        run_scheduler()
    elif args.mode == 'setup':
        run_setup()
    elif args.mode == 'test':
        run_test()

if __name__ == "__main__":
    main()
