from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import psycopg2
import psycopg2.extras
from psycopg2.extras import RealDictCursor
from flask import flash
import os
import random
from werkzeug.utils import secure_filename
import firebase_admin
from firebase_admin import credentials, messaging
from pyfcm import FCMNotification
from flask import send_from_directory
import cloudinary
import cloudinary.uploader
import cloudinary.api
from functools import wraps
import uuid
import random
from datetime import timedelta, datetime
import threading
import time


# after your other imports, before using Cloudinary
cloudinary.config(
  cloud_name = "dqfombatw",
  api_key    = "731637769665287",
  api_secret = "e-d0C1VEJm5Dj-40EM0jNF5kjvk"
)


app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "fallback_secret_key")

# Increase file upload size limit to 16MB
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB

# Keep sessions alive for 30 days
app.permanent_session_lifetime = timedelta(days=365*10)

@app.before_request
def make_session_permanent():
    session.permanent = True

# Base paths
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATABASE_URL = "postgresql://postgres.beuvyrvloopqgffoscrd:karthik57@aws-0-ap-south-1.pooler.supabase.com:6543/postgres"
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def generate_unique_helperid(cursor):
    while True:
        helperid = ''.join([str(random.randint(0, 9)) for _ in range(10)])  # Generate 10-digit number
        cursor.execute("SELECT 1 FROM users WHERE helperid = %s", (helperid,))
        if not cursor.fetchone():
            return helperid

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def validate_file_size(file):
    """Validate file size (max 10MB)"""
    if file:
        file.seek(0, 2)  # Seek to end
        size = file.tell()
        file.seek(0)  # Reset to beginning
        return size <= 10 * 1024 * 1024  # 10MB limit
    return True

def upload_to_cloudinary(file_storage):
    result = cloudinary.uploader.upload(
        file_storage,
        folder="helper/profile_pics",    # optional organization
        public_id=str(uuid.uuid4()),       # avoid name collisions
        overwrite=False,
        resource_type="image"
    )
    return result["secure_url"]

@app.context_processor
def inject_logged_in_user():
    if 'username' in session:
        with get_db_connection() as conn:
            cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cursor.execute("SELECT * FROM users WHERE username = %s", (session['username'],))
            logged_in_user = cursor.fetchone()
            return dict(logged_in_user=logged_in_user)
    return dict(logged_in_user=None)

def get_db_connection():
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    return conn

def ensure_notifications_schema():
    """Ensure notifications table has required columns (type, link)"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            # Check and add type column
            cursor.execute("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name='notifications' AND column_name='type'
            """)
            if not cursor.fetchone():
                cursor.execute("ALTER TABLE notifications ADD COLUMN type TEXT")
            # Check and add link column
            cursor.execute("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name='notifications' AND column_name='link'
            """)
            if not cursor.fetchone():
                cursor.execute("ALTER TABLE notifications ADD COLUMN link TEXT")
            conn.commit()
    except Exception as e:
        print(f"Schema check error (may be harmless): {e}")


# Initialize Firebase Admin SDK
cred = credentials.Certificate("firebase-service-account-key.json")
firebase_admin.initialize_app(cred)

def send_push_notification(token, title, body):
    # Send a Web Push-friendly notification (works for web FCM tokens)
    message = messaging.Message(
        notification=messaging.Notification(title=title, body=body),
        webpush=messaging.WebpushConfig(
            notification=messaging.WebpushNotification(
                title=title,
                body=body,
                icon='/static/assets/mrhelperlogo.jpg',
                actions=[messaging.WebpushNotificationAction('open', 'Open')]
            ),
            fcm_options=messaging.WebpushFCMOptions(link='/notifications'),
            headers={
                'TTL': '2419200'  # up to 4 weeks
            },
            data={
                'title': title,
                'body': body,
                'url': '/notifications'
            }
        ),
        token=token,
    )
    try:
        response = messaging.send(message)
        print('Successfully sent message:', response)
    except Exception as e:
        print(f'Error sending message: {e}')

@app.route('/debug-push')
def debug_push():
    if 'username' not in session:
        return redirect(url_for('login'))
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT fcm_token FROM users WHERE username = %s", (session['username'],))
        row = cur.fetchone()
        if not row or not row[0]:
            flash('No FCM token found for your account. Open the site and allow notifications first.', 'warning')
            return redirect(url_for('home'))
        token = row[0]
    try:
        send_push_notification(token, 'Test Notification', 'This is a test push from Mr. Helper')
        flash('Test push sent. Check your device notification tray.', 'success')
    except Exception as e:
        print('Debug push error:', e)
        flash('Failed to send test push. Check server logs.', 'error')
    return redirect(url_for('home'))

def init_db():
    with get_db_connection() as conn:
        cursor = conn.cursor()

        # Create the 'users' table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username TEXT UNIQUE,
                password TEXT,
                account_type TEXT,
                phone TEXT,
                business_type TEXT,
                location TEXT,
                bio TEXT,
                profile_pic TEXT,
                price TEXT
            )
        ''')
        
        # Create subscription_plans table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS subscription_plans (
                id SERIAL PRIMARY KEY,
                category TEXT UNIQUE NOT NULL,
                amount NUMERIC NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Create subscriptions table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS subscriptions (
                id SERIAL PRIMARY KEY,
                helper_username TEXT NOT NULL,
                category TEXT NOT NULL,
                start_date DATE NOT NULL,
                end_date DATE NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                total_due NUMERIC DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Add total_due column if it doesn't exist
        try:
            cursor.execute("ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS total_due NUMERIC DEFAULT 0")
        except Exception:
            pass
        
        # Create order_requests table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS order_requests (
                id SERIAL PRIMARY KEY,
                order_id INTEGER NOT NULL,
                helper_username TEXT NOT NULL,
                amount NUMERIC NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                timestamp TIMESTAMP DEFAULT NOW(),
                UNIQUE(order_id, helper_username)
            )
        ''')
        
        # Create order_otps table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS order_otps (
                id SERIAL PRIMARY KEY,
                order_id INTEGER NOT NULL,
                otp TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT NOW(),
                expires_at TIMESTAMP NOT NULL,
                is_verified BOOLEAN DEFAULT FALSE,
                verified_at TIMESTAMP
            )
        ''')
        
        # Create helper_fines table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS helper_fines (
                id SERIAL PRIMARY KEY,
                helper_username TEXT NOT NULL,
                order_id INTEGER NOT NULL,
                fine_amount NUMERIC DEFAULT 0,
                status TEXT DEFAULT 'unpaid',
                fine_reason TEXT,
                created_at TIMESTAMP DEFAULT NOW(),
                paid_at TIMESTAMP
            )
        ''')
        
        # Create notifications table if it doesn't exist
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS notifications (
                id SERIAL PRIMARY KEY,
                from_user_id INTEGER,
                to_user_id INTEGER,
                order_id INTEGER,
                message TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_read BOOLEAN DEFAULT FALSE,
                type TEXT,
                link TEXT
            )
        ''')
        
        # Add type column if it doesn't exist (for existing databases)
        try:
            cursor.execute("""
                DO $$ 
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns 
                        WHERE table_name='notifications' AND column_name='type'
                    ) THEN
                        ALTER TABLE notifications ADD COLUMN type TEXT;
                    END IF;
                END $$;
            """)
        except Exception as e:
            # Fallback: try direct ALTER if DO block fails (older PostgreSQL)
            try:
                cursor.execute("ALTER TABLE notifications ADD COLUMN type TEXT")
            except Exception:
                pass
        
        # Add link column if it doesn't exist (for existing databases)
        try:
            cursor.execute("""
                DO $$ 
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns 
                        WHERE table_name='notifications' AND column_name='link'
                    ) THEN
                        ALTER TABLE notifications ADD COLUMN link TEXT;
                    END IF;
                END $$;
            """)
        except Exception as e:
            # Fallback: try direct ALTER if DO block fails (older PostgreSQL)
            try:
                cursor.execute("ALTER TABLE notifications ADD COLUMN link TEXT")
            except Exception:
                pass
        
        # Create order_negotiations table for tracking negotiation history
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS order_negotiations (
                id SERIAL PRIMARY KEY,
                order_id INTEGER NOT NULL,
                sender_id INTEGER NOT NULL,
                receiver_id INTEGER NOT NULL,
                price NUMERIC,
                action TEXT,
                message TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Add order verification status and progress tracking columns
        try:
            cursor.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS is_verified BOOLEAN DEFAULT FALSE")
            cursor.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS verified_at TIMESTAMP")
            cursor.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS verification_deadline TIMESTAMP")
            cursor.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS user_action TEXT")
            cursor.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS user_action_at TIMESTAMP")
            cursor.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS verification_helper_id INTEGER")
            # Booking/Nego fields
            cursor.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS user_id INTEGER")
            cursor.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS helper_id INTEGER")
            cursor.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS about TEXT")
            cursor.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS image_url TEXT")
            cursor.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'pending'")
            cursor.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS price NUMERIC")
            cursor.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS otp TEXT")
            cursor.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS otp_expires_at TIMESTAMP")
            cursor.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
            cursor.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS is_direct_booking BOOLEAN DEFAULT FALSE")
            cursor.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS otp_attempts INTEGER DEFAULT 0")
        except Exception:
            pass
        
        conn.commit()

# Routes
# ---------- ROOT ----------
@app.route('/')
def root():
    if 'username' in session:
        if session['username'] == 'adime':
            return redirect(url_for('admin_dashboard'))
        return redirect(url_for('login'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'username' in session:
        # If already logged in, go to home
        if session['username'] == 'adime':
            return redirect(url_for('admin_dashboard'))
        else:
            return redirect(url_for('home'))

    if request.method == 'POST':
        username = request.form['username'].strip() 
        password = request.form['password']

        if username == 'adime' and password == 'adime123':
            session['username'] = username
            return redirect(url_for('admin_dashboard'))

        with get_db_connection() as conn:
            cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cursor.execute("SELECT * FROM users WHERE username=%s AND password=%s", (username, password))
            user = cursor.fetchone()
            if user:
                session['username'] = username
                return redirect(url_for('home'))
            else:
                flash("Invalid username or password", "danger")
                return render_template('login.html')

    # Not logged in and not posting — show login page
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('username', None)
    return redirect(url_for('login'))

@app.route('/home')
def home():
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # New: Fetch 6 random business types for homepage cards
        try:
            cursor.execute(
                """
                SELECT id, name, image
                FROM business_types
                ORDER BY RANDOM()
                LIMIT 6
                """
            )
            random_business_types = cursor.fetchall()
        except Exception:
            # Fallback if table doesn't exist yet: derive from users
            cursor.execute(
                """
                SELECT NULL::int as id, business_type as name, NULL::text as image
                FROM (
                    SELECT DISTINCT business_type
                    FROM users
                    WHERE account_type='business' AND business_type IS NOT NULL AND business_type <> ''
                ) t
                ORDER BY RANDOM()
                LIMIT 6
                """
            )
            random_business_types = cursor.fetchall()

        # Get services from database
        cursor.execute("SELECT DISTINCT business_type FROM users WHERE account_type='business'")
        services_from_db = [row['business_type'] for row in cursor.fetchall()]

        # Get ads
        cursor.execute("SELECT * FROM ads ORDER BY created_at DESC")
        ads = cursor.fetchall()

        # Get business usernames for search
        cursor.execute("SELECT username FROM users WHERE account_type='business'")
        business_usernames = [row['username'] for row in cursor.fetchall()]

        # Get recent activity (bookings today)
        cursor.execute("""
            SELECT COUNT(*) as daily_bookings 
            FROM orders 
            WHERE DATE(created_at) = CURRENT_DATE
        """)
        daily_bookings = cursor.fetchone()['daily_bookings']

        # Get total helpers count
        cursor.execute("SELECT COUNT(*) as total_helpers FROM users WHERE account_type='business'")
        total_helpers = cursor.fetchone()['total_helpers']

        # Get featured helpers (top rated)
        cursor.execute("""
            SELECT username, business_type, location, avg_rating, profile_pic, price_numeric as price
            FROM users 
            WHERE account_type='business' AND avg_rating IS NOT NULL AND avg_rating > 0
            ORDER BY avg_rating DESC 
            LIMIT 6
        """)
        featured_helpers = cursor.fetchall()

        # Get service counts for each category
        cursor.execute("""
            SELECT business_type, COUNT(*) as helper_count, 
                   AVG(COALESCE(price_numeric, 0)) as avg_price, AVG(COALESCE(avg_rating, 0)) as avg_rating
            FROM users 
            WHERE account_type='business' 
            GROUP BY business_type
        """)
        service_stats = {row['business_type']: {
            'helper_count': row['helper_count'],
            'avg_price': row['avg_price'] or 0,
            'avg_rating': row['avg_rating'] or 0
        } for row in cursor.fetchall()}

        # Get trending services (most booked today)
        cursor.execute("""
            SELECT s.service_name, COUNT(o.id) as booking_count
            FROM orders o
            JOIN services s ON s.id = o.service_id
            WHERE DATE(o.created_at) = CURRENT_DATE
            GROUP BY s.service_name
            ORDER BY booking_count DESC
            LIMIT 5
        """)
        trending_services = [row['service_name'] for row in cursor.fetchall()]

    predefined_services = [
        'Cleaning',
        'Plumbing','Carpentry','Electrician', 'Vehicle','Painting'
    ]
    all_services = list(set(services_from_db + predefined_services))
    random.shuffle(all_services)
    random_services = all_services[:6]

    service_images = {
        'Cleaning': 'cleaning.jpg',
        'Plumbing': 'cleaning.jpg',
        'Electrician': 'electrical.jpg',
        'Vehicle': 'electrical.jpg',
        'Painting': 'painting.jpg',
        'Carpentry': 'carpentry.jpg'
    }

    # Service descriptions and pricing
    service_descriptions = {
        'Cleaning': 'Professional house cleaning and maintenance services',
        'Plumbing': 'Expert plumbing repairs and installations',
        'Electrician': 'Licensed electrical work and repairs',
        'Vehicle': 'Auto repair and maintenance services',
        'Painting': 'Interior and exterior painting services',
        'Carpentry': 'Custom woodwork and furniture repair'
    }

    # Ensure we always have a valid asset filename to avoid 404 on '/static/assets/'
    random_service_images = {service: service_images.get(service, 'default_camera.jpg') for service in random_services}

    # Ensure we always have 6 cards; if business types are empty, fallback to random services
    if not random_business_types:
        random_business_types = [
            { 'id': None, 'name': svc, 'image': url_for('static', filename='assets/' + random_service_images.get(svc, 'default_category.jpg')) }
            for svc in random_services
        ]

    return render_template(
        'home.html',
        services=random_services,
        service_images=random_service_images,
        business_usernames=business_usernames,
        ads=ads,
        daily_bookings=daily_bookings,
        total_helpers=total_helpers,
        featured_helpers=featured_helpers,
        service_stats=service_stats,
        trending_services=trending_services,
        service_descriptions=service_descriptions,
        business_types=random_business_types
    )

@app.route('/search', methods=['GET', 'POST'])
def search():
    query = request.args.get('q', '')  # Get the search query from the URL parameters
    services = []
    business_users = []
    locations = []
    trending_services = []

    # Get trending services for popular searches
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        # Get trending services from recent orders
        cursor.execute("""
            SELECT s.service_name, COUNT(o.id) as order_count
            FROM orders o
            JOIN services s ON s.id = o.service_id
            WHERE o.created_at >= CURRENT_DATE - INTERVAL '7 days'
            GROUP BY s.service_name
            ORDER BY order_count DESC
            LIMIT 6
        """)
        trending_services = [row['service_name'] for row in cursor.fetchall()]

        if query:
            # Search for services
            cursor.execute("""
                SELECT * FROM services
                WHERE service_name ILIKE %s
            """, (f'%{query}%',))
            services = cursor.fetchall()

            # Search for businesses based on location and business type
            cursor.execute("""
                SELECT username, business_type, location, price, profile_pic, avg_rating FROM users
                WHERE (username ILIKE %s OR location ILIKE %s OR business_type ILIKE %s) AND account_type = 'business'
            """, (f'%{query}%', f'%{query}%', f'%{query}%'))
            business_users = cursor.fetchall()

            # Search for locations
            cursor.execute("""
                SELECT * FROM locations
                WHERE location_name ILIKE %s
            """, (f'%{query}%',))
            locations = cursor.fetchall()

    return render_template('search.html', 
                       query=query, 
                       service_results=services, 
                       business_results=business_users,
                       location_results=locations,
                       trending_services=trending_services)

# ---------- ADMIN ----------
@app.route('/admin')
def admin_dashboard():
    if 'username' not in session or session['username'] != 'adime':
        flash('Access denied: Admins only.', 'danger')
        return redirect(url_for('login'))

    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cursor.execute("SELECT * FROM users WHERE username != 'adime'")
        users = cursor.fetchall()

        cursor.execute("SELECT * FROM kyc")
        kyc_requests = cursor.fetchall()

        cursor.execute("SELECT reported_user, COUNT(*) as report_count FROM reports GROUP BY reported_user")
        reported_users = cursor.fetchall()

        # NEW: fetch all ads for admin control
        cursor.execute("SELECT id, name, image_url, ad_url, created_at FROM ads ORDER BY id DESC")
        ads = cursor.fetchall()

    return render_template(
        'adime.html',
        users=users,
        reported_users=reported_users,
        kyc_requests=kyc_requests,
        ads=ads   # pass ads to template
    )
@app.route('/admin/kyc/accept/<username>', methods=['POST'])
def accept_kyc(username):
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute("SELECT * FROM kyc WHERE username = %s", (username,))
        user = cursor.fetchone()

        if user:
            cursor.execute("""
                INSERT INTO users 
                (username, password, gender, account_type, phone, gmail, business_type, service_type,
                housenumber, street, landmark, location, bio, price, profile_pic, helperid,
                aadhaar_file, pan_file) 
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                user['username'], user['password'], user['gender'], 'business',
                user['phone'], user['gmail'],
                user['business_type'], user['service_type'],
                user['housenumber'], user['street'], user['landmark'], user['location'],
                user['bio'], user['price'],
                user['profile_pic'], user['helperid'],
                user['aadhaar_file'], user['pan_file']
            ))

            # Clean up from KYC
            cursor.execute("DELETE FROM kyc WHERE username = %s", (username,))
            conn.commit()
    
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/kyc/reject/<username>', methods=['POST'])
def reject_kyc(username):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM kyc WHERE username = %s", (username,))
        conn.commit()
    
    return redirect(url_for('admin_dashboard'))

@app.route('/delete_user/<username>', methods=['POST'])
def delete_user(username):
    if 'username' not in session or session['username'] != 'adime':
        return redirect(url_for('login'))

    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        try:
            # Get the user's ID first
            cursor.execute("SELECT id FROM users WHERE username=%s", (username,))
            user_result = cursor.fetchone()
            
            if not user_result:
                flash("User not found.", "error")
                return redirect(url_for('admin_dashboard'))
            
            user_id = user_result[0]
            
            # Get all orders owned by this user
            cursor.execute("SELECT id FROM orders WHERE owner_id=%s", (user_id,))
            order_ids = [row[0] for row in cursor.fetchall()]
            
            # Delete related records in the correct order to avoid foreign key violations
            if order_ids:
                # Build placeholder string for IN clause
                placeholders = ','.join(['%s'] * len(order_ids))
                
                # Delete order_acceptance records that reference these orders
                cursor.execute(f"""
                    DELETE FROM order_acceptance 
                    WHERE order_id IN ({placeholders})
                """, tuple(order_ids))
                
                # Delete order_requests records that reference these orders
                cursor.execute(f"""
                    DELETE FROM order_requests 
                    WHERE order_id IN ({placeholders})
                """, tuple(order_ids))
                
                # Delete notifications that reference these orders
                cursor.execute(f"""
                    DELETE FROM notifications 
                    WHERE order_id IN ({placeholders})
                """, tuple(order_ids))
            
            # Also delete order_acceptance records where user is a provider
            cursor.execute("DELETE FROM order_acceptance WHERE provider_id=%s", (user_id,))
            
            # Delete notifications where user is the recipient or sender
            cursor.execute("DELETE FROM notifications WHERE to_user_id=%s OR from_user_id=%s", (user_id, user_id))
            
            # Delete subscriptions for this user
            cursor.execute("DELETE FROM subscriptions WHERE helper_username=%s", (username,))
            
            # Delete ratings for this user (if ratings table exists, ignore if it doesn't)
            # Check if ratings table exists first
            cursor.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'ratings'
                )
            """)
            ratings_table_exists = cursor.fetchone()[0]
            
            if ratings_table_exists:
                cursor.execute("""
                    DELETE FROM ratings 
                    WHERE rater_id=%s OR rated_user_id=%s
                """, (user_id, user_id))
            
            # Now delete the user (this will cascade delete orders if FK is set up with CASCADE)
            cursor.execute("DELETE FROM users WHERE username=%s", (username,))
            conn.commit()
            flash("User deleted successfully.", "success")
            
        except Exception as e:
            conn.rollback()
            flash(f"Error deleting user: {str(e)}", "error")
            import traceback
            traceback.print_exc()
    
    return redirect(url_for('admin_dashboard'))

# Route: Upload Ads (Admin only)
@app.route('/upload_ad', methods=['POST'])
def upload_ad():
    if 'username' not in session or session['username'] != 'adime':
        return redirect(url_for('login'))

    name = request.form.get('name', '').strip()
    ad_url = request.form.get('url', '').strip() or None  # matches your form name="url"
    image = request.files.get('image')

    if not name or not image:
        flash("Ad name and image are required.", "danger")
        return redirect(url_for('admin_dashboard'))

    # Upload image to Cloudinary (uses your existing helper)
    image_url = upload_to_cloudinary(image)

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO ads (name, image_url, ad_url) VALUES (%s, %s, %s)",
                (name, image_url, ad_url)
            )
            conn.commit()

    flash("Ad uploaded successfully.", "success")
    return redirect(url_for('admin_dashboard'))

# Route: Delete Ad (Admin only)
@app.route('/delete_ad/<int:ad_id>', methods=['POST'])
def delete_ad(ad_id):
    if 'username' not in session or session['username'] != 'adime':
        return redirect(url_for('login'))

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM ads WHERE id = %s", (ad_id,))
            conn.commit()

    flash("Ad deleted.", "success")
    return redirect(url_for('admin_dashboard'))

# Route: Subscription Plans Management (Admin only)
@app.route('/admin/subscription-plans')
def admin_subscription_plans():
    """Manage subscription plans"""
    if 'username' not in session or session['username'] != 'adime':
        flash('Access denied: Admins only.', 'danger')
        return redirect(url_for('login'))
    
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        # Get all plans
        cur.execute("SELECT * FROM subscription_plans ORDER BY category")
        plans = cur.fetchall()
        
        # Get all unique categories from users
        cur.execute("SELECT DISTINCT business_type FROM users WHERE account_type='business' ORDER BY business_type")
        categories = cur.fetchall()
        
    return render_template('admin_subscription_plans.html', plans=plans, categories=categories)

@app.route('/admin/subscription-plans/create', methods=['POST'])
def create_subscription_plan():
    """Create a new subscription plan"""
    if 'username' not in session or session['username'] != 'adime':
        flash('Access denied: Admins only.', 'danger')
        return redirect(url_for('login'))
    
    category = request.form.get('category')
    amount = request.form.get('amount')
    
    if not category or not amount:
        flash("Category and amount are required.", "error")
        return redirect(url_for('admin_subscription_plans'))
    
    try:
        amount = float(amount)
    except ValueError:
        flash("Invalid amount.", "error")
        return redirect(url_for('admin_subscription_plans'))
    
    with get_db_connection() as conn:
        cur = conn.cursor()
        
        # Insert or update plan
        cur.execute("""
            INSERT INTO subscription_plans (category, amount)
            VALUES (%s, %s)
            ON CONFLICT (category) 
            DO UPDATE SET amount = EXCLUDED.amount
        """, (category, amount))
        conn.commit()
    
    flash(f"Subscription plan for {category} updated successfully!", "success")
    return redirect(url_for('admin_subscription_plans'))

@app.route('/admin/subscription-plans/delete/<int:plan_id>', methods=['POST'])
def delete_subscription_plan(plan_id):
    """Delete a subscription plan"""
    if 'username' not in session or session['username'] != 'adime':
        flash('Access denied: Admins only.', 'danger')
        return redirect(url_for('login'))
    
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM subscription_plans WHERE id = %s", (plan_id,))
        conn.commit()
    
    flash("Subscription plan deleted successfully!", "success")
    return redirect(url_for('admin_subscription_plans'))

@app.route('/admin/order-requests')
def admin_order_requests():
    """Admin monitoring of order requests"""
    if 'username' not in session or session['username'] != 'adime':
        flash('Access denied: Admins only.', 'danger')
        return redirect(url_for('login'))
    
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        # Get all order requests with details
        cur.execute("""
            SELECT 
                or_req.*,
                o.message as order_message,
                s.service_name,
                l.location_name,
                (SELECT username FROM users WHERE id = o.owner_id) as customer_username
            FROM order_requests or_req
            JOIN orders o ON o.id = or_req.order_id
            JOIN services s ON s.id = o.service_id
            JOIN locations l ON l.id = o.location_id
            ORDER BY or_req.timestamp DESC
        """)
        requests = cur.fetchall()
    
    return render_template('admin_order_requests.html', requests=requests)

@app.route('/admin/order-requests/delete/<int:request_id>', methods=['POST'])
def delete_order_request(request_id):
    """Delete an order request"""
    if 'username' not in session or session['username'] != 'adime':
        flash('Access denied: Admins only.', 'danger')
        return redirect(url_for('login'))
    
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM order_requests WHERE id = %s", (request_id,))
        conn.commit()
    
    flash("Order request deleted successfully!", "success")
    return redirect(url_for('admin_order_requests'))

@app.route('/signup')
def signup():
    return render_template('signup.html')
@app.route('/signup/business', methods=['GET', 'POST'])
def signup_business():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password'].strip()
        phone = request.form['phone']
        gender = request.form['gender']
        gmail = request.form['gmail'] 
        business_type = request.form['business_type']
        service_type = request.form['service_type']
        housenumber = request.form['housenumber']
        street = request.form['street']
        landmark = request.form['landmark']
        location = request.form['location']
        bio = request.form.get('bio', '')
        price = request.form.get('price', '')

        # File uploads
        profile_pic_file = request.files.get('profile_pic')
        aadhaar_file = request.files.get('aadhaar_card')
        pan_file = request.files.get('pan_card')

        profile_filename = aadhaar_filename = pan_filename = ''

        if profile_pic_file and allowed_file(profile_pic_file.filename):
            profile_filename = upload_to_cloudinary(profile_pic_file)

        if aadhaar_file and allowed_file(aadhaar_file.filename):
            aadhaar_filename = upload_to_cloudinary(aadhaar_file)

        if pan_file and allowed_file(pan_file.filename):
            pan_filename = upload_to_cloudinary(pan_file)

        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()

                # Check username uniqueness
                cursor.execute("SELECT 1 FROM users WHERE username = %s UNION SELECT 1 FROM kyc WHERE username = %s", 
                               (username, username))
                if cursor.fetchone():
                    flash('Username is already taken.', 'error')
                    return render_template('signup_business.html')

                # Generate helper ID
                helperid = generate_unique_helperid(cursor)

                # Insert into KYC
                cursor.execute("""
                    INSERT INTO kyc 
                    (username, password, gender, phone, gmail, business_type, service_type,housenumber,street,landmark, location, bio, price, profile_pic, aadhaar_file, pan_file, helperid)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,%s, %s, %s)
                """, (username, password, gender, phone, gmail, business_type, service_type,housenumber,street,landmark, location, bio, price, 
                      profile_filename, aadhaar_filename, pan_filename, helperid))

                # Insert into services/locations if new
                cursor.execute("INSERT INTO services (service_name) VALUES (%s) ON CONFLICT DO NOTHING", (business_type,))
                cursor.execute("INSERT INTO locations (location_name) VALUES (%s) ON CONFLICT DO NOTHING", (location,))
                conn.commit()

                flash("Our team will connect for KYC.", "success")
                return redirect(url_for('login'))  # redirect after success

        except Exception as e:
            print(f"Error: {e}")
            flash('An error occurred during registration. Please try again.', 'error')

    return render_template('signup_business.html')

@app.route('/signup/user', methods=['GET', 'POST'])
def signup_user():
    error = None
    if request.method == 'POST':        
        username = request.form['username'].strip()
        password = request.form['password'].strip()
        gender = request.form['gender']
        gmail = request.form['gmail']  # FIX: changed () to []
        phone = request.form['phone']
        housenumber = request.form['housenumber']
        street = request.form['street']
        landmark = request.form['landmark']
        location = request.form['location']

        profile_pic_file = request.files.get('profile_pic')
        filename = ''
        if profile_pic_file and allowed_file(profile_pic_file.filename):
            filename = upload_to_cloudinary(profile_pic_file)

        with get_db_connection() as conn:
            cursor = conn.cursor()
             # Check if the username already exists
            cursor.execute("SELECT 1 FROM users WHERE username = %s", (username,))
            if cursor.fetchone():
                flash('Username is already taken.', 'danger')
                return render_template('signup_user.html')
            else:
                try:
                    cursor.execute("INSERT INTO users (username, password, gender, account_type, phone, gmail, housenumber,street,landmark, location, profile_pic) VALUES (%s, %s,%s,%s,%s,%s,%s, %s,%s, %s, %s)", 
                                (username, password,gender, 'user', phone, gmail, housenumber,street,landmark, location, filename))
                    conn.commit()
                    return redirect(url_for('login'))
                except psycopg2.IntegrityError:
                    error = "An error occurred. Please try again."
    return render_template('signup_user.html', error=error)

@app.route('/profile')
@app.route('/profile/<username>')
def profile(username=None):
    if 'username' not in session:
        return redirect(url_for('login'))

    # Logged-in user (always from session)
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute("SELECT * FROM users WHERE username = %s", (session['username'],))
        logged_in_user = cursor.fetchone()

        # Target profile (could be yourself or another user)
        if username is None:
            username = session['username']
        cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
        profile_user = cursor.fetchone()

        if not profile_user:
            flash("User not found.")
            return redirect(url_for('login'))

        # Feedback for average rating with usernames
        cursor.execute("""
            SELECT f.*, u.username as from_user
            FROM feedback f
            JOIN users u ON u.id = f.from_user_id
            WHERE f.to_user_id = %s
        """, (profile_user['id'],))
        feedback = cursor.fetchall()
        total_rating = sum([fb['rating'] for fb in feedback])
        rating_count = len(feedback)
        average_rating = round(total_rating / rating_count, 1) if rating_count > 0 else None

        # Has logged-in user already rated this profile?
        has_rated = False
        if session['username'] != username:
            cursor.execute("SELECT id FROM users WHERE username = %s", (session['username'],))
            session_user = cursor.fetchone()
            if session_user:
                cursor.execute("""
                    SELECT 1 FROM feedback
                    WHERE to_user_id = %s AND from_user_id = %s
                """, (profile_user['id'], session_user['id']))
                has_rated = cursor.fetchone() is not None

        # Reports
        cursor.execute("SELECT * FROM reports WHERE reported_user = %s", (username,))
        reports = cursor.fetchall()

        # Ownership and admin check
        is_owner = session['username'] == username
        is_admin = session['username'] == 'adime'

        # If admin viewing a business profile, fetch subscriptions for management UI
        subscriptions = []
        if is_admin and profile_user.get('account_type') == 'business':
            cursor.execute("""
                SELECT id, helper_username, category, status, start_date, end_date
                FROM subscriptions
                WHERE helper_username = %s
                ORDER BY status DESC, end_date DESC NULLS LAST
            """, (profile_user['username'],))
            subscriptions = cursor.fetchall()

    return render_template(
        'profile.html',
        logged_in_user=logged_in_user,   # ✅ always the session user
        profile_user=profile_user,       # ✅ profile being visited
        feedback=feedback,
        average_rating=average_rating,
        rating_count=rating_count,
        has_rated=has_rated,
        reports=reports,
        is_owner=is_owner,
        is_admin=is_admin,
        subscriptions=subscriptions
    )

@app.route('/edit_profile', methods=['GET', 'POST'])
def edit_profile():
    if 'username' not in session:
        return redirect(url_for('login'))

    username = session['username']
    
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        if request.method == 'POST':
            bio = request.form.get('bio', '')
            price = request.form.get('price', '')
            phone = request.form.get('phone', '')
            location = request.form.get('location', '')
            street = request.form.get('street', '')

            # Handle profile picture update (camera capture for helpers, file upload for users)
            profile_pic_file = request.files.get('profile_pic')
            filename = None
            
            # Check if user is a helper (business account)
            cursor.execute("SELECT account_type FROM users WHERE username = %s", (username,))
            account_type_result = cursor.fetchone()
            is_helper = account_type_result and account_type_result.get('account_type') == 'business'
            
            if profile_pic_file and allowed_file(profile_pic_file.filename):
                filename = upload_to_cloudinary(profile_pic_file)

            # Update user details based on account type
            if filename:
                if is_helper:
                    # Helper: update all fields including price
                    cursor.execute("""
                        UPDATE users SET bio=%s, price=%s, profile_pic=%s, phone=%s, location=%s, street=%s WHERE username=%s
                    """, (bio, price, filename, phone, location, street, username))
                else:
                    # User: update without price
                    cursor.execute("""
                        UPDATE users SET bio=%s, profile_pic=%s, phone=%s, location=%s, street=%s WHERE username=%s
                    """, (bio, filename, phone, location, street, username))
            else:
                if is_helper:
                    # Helper: update without profile pic but with price
                    cursor.execute("""
                        UPDATE users SET bio=%s, price=%s, phone=%s, location=%s, street=%s WHERE username=%s
                    """, (bio, price, phone, location, street, username))
                else:
                    # User: update without profile pic and without price
                    cursor.execute("""
                        UPDATE users SET bio=%s, phone=%s, location=%s, street=%s WHERE username=%s
                    """, (bio, phone, location, street, username))

            conn.commit()
            flash('Profile updated successfully.', 'success')
            return redirect(url_for('profile', username=username))

        # For GET request, fetch current data
        cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
        user = cursor.fetchone()
        if not user:
            flash('User not found.', 'danger')
            return redirect(url_for('home'))

    return render_template('edit_profile.html', user=user)

@app.route("/book_helper/<int:helper_id>", methods=["POST"])
@login_required
def book_helper(helper_id):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    try:
        # --- 1️⃣ Ensure user_id exists in session ---
        user_id = session.get("user_id")
        if not user_id:
            cursor.execute("SELECT id FROM users WHERE username = %s", (session["username"],))
            user = cursor.fetchone()
            if not user:
                return jsonify({"success": False, "message": "User not found"}), 404
            user_id = user["id"]

        # --- 2️⃣ Collect form data ---
        about = request.form.get("message", "").strip()  # "About the order" field
        price = request.form.get("price", "").strip()
        photo = request.files.get("photo")

        if not about or not price:
            return jsonify({"success": False, "message": "Order description and price are required"}), 400

        try:
            price = float(price)
            if price <= 0:
                return jsonify({"success": False, "message": "Price must be greater than 0"}), 400
        except ValueError:
            return jsonify({"success": False, "message": "Invalid price format"}), 400

        # --- 3️⃣ Check for duplicate pending bookings ---
        cursor.execute("""
            SELECT id FROM orders 
            WHERE user_id = %s AND helper_id = %s AND status = 'pending' AND is_direct_booking = TRUE
        """, (user_id, helper_id))
        existing = cursor.fetchone()
        if existing:
            return jsonify({"success": False, "message": "You already have a pending booking with this helper"}), 400

        # --- 4️⃣ Check helper subscription ---
        cursor.execute("""
            SELECT id, username, account_type, location, business_type FROM users WHERE id = %s
        """, (helper_id,))
        helper = cursor.fetchone()
        if not helper:
            return jsonify({"success": False, "message": "Helper not found"}), 404

        if helper["account_type"] != "business":
            return jsonify({"success": False, "message": "This user is not a helper"}), 400

        # Check if helper has active subscription
        cursor.execute("""
            SELECT 1 FROM subscriptions 
            WHERE helper_username = %s 
                AND category = %s 
                AND status = 'active' 
                AND end_date >= CURRENT_DATE
        """, (helper["username"], helper["business_type"]))
        has_subscription = cursor.fetchone()
        
        if not has_subscription:
            return jsonify({"success": False, "message": "Helper not available right now."}), 400

        # --- 5️⃣ Handle optional image upload ---
        image_url = None
        if photo and photo.filename:
            filename = secure_filename(photo.filename)
            upload_dir = os.path.join("static", "uploads")
            os.makedirs(upload_dir, exist_ok=True)
            # Add timestamp to avoid conflicts
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{timestamp}_{filename}"
            save_path = os.path.join(upload_dir, filename)
            photo.save(save_path)
            image_url = f"/{save_path.replace(os.sep, '/')}"

        # --- 6️⃣ Get related service/location IDs (optional for direct bookings) ---
        cursor.execute(
            "SELECT id FROM services WHERE service_name = %s LIMIT 1",
            (helper["business_type"],),
        )
        service = cursor.fetchone()
        service_id = service["id"] if service else None

        cursor.execute(
            "SELECT id FROM locations WHERE location_name = %s LIMIT 1",
            (helper["location"],),
        )
        loc = cursor.fetchone()
        location_id = loc["id"] if loc else None

        # --- 7️⃣ Insert order ---
        cursor.execute(
            """
            INSERT INTO orders (
                user_id, helper_id, about, image_url,
                price, status, is_direct_booking, service_id, location_id, created_at
            )
            VALUES (%s, %s, %s, %s, %s, 'pending', TRUE, %s, %s, NOW())
            RETURNING id
            """,
            (user_id, helper_id, about, image_url, price, service_id, location_id),
        )
        order_id = cursor.fetchone()["id"]

        # --- 8️⃣ Store negotiation history ---
        cursor.execute("""
            INSERT INTO order_negotiations (order_id, sender_id, receiver_id, price, action, message)
            VALUES (%s, %s, %s, %s, 'initial_offer', %s)
        """, (order_id, user_id, helper_id, price, about))

        # --- 9️⃣ Ensure schema is up to date ---
        ensure_notifications_schema()
        
        # --- 🔟 Insert notification with booking details ---
        notification_message = f"📋 New booking request from {session['username']}\n\nPrice offered: ₹{price}\nOrder details: {about[:100]}{'...' if len(about) > 100 else ''}"
        cursor.execute(
            """
            INSERT INTO notifications (from_user_id, to_user_id, order_id, message, type, created_at, is_read)
            VALUES (%s, %s, %s, %s, 'booking_request', NOW(), FALSE)
            """,
            (user_id, helper_id, order_id, notification_message),
        )

        conn.commit()
        return jsonify({"success": True, "message": "Booking request sent successfully."})

    except Exception as e:
        conn.rollback()
        import traceback
        print("Error in /book_helper:", e)
        traceback.print_exc()
        return jsonify({"success": False, "message": "Server error: " + str(e)}), 500

    finally:
        cursor.close()
        conn.close()

@app.route("/helper_response/<int:order_id>", methods=["POST"])
@login_required
def helper_response(order_id):
    try:
        data = request.get_json()
        action = data.get("action")
        price = data.get("price")

        # --- 1️⃣ Get user ID safely ---
        user_id = session.get("user_id")
        if not user_id:
            conn = get_db_connection()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("SELECT id FROM users WHERE username = %s", (session["username"],))
            user = cur.fetchone()
            cur.close()
            conn.close()
            if not user:
                return jsonify({"success": False, "message": "User not found."}), 404
            user_id = user["id"]

        username = session["username"]

        # --- 2️⃣ DB Operations ---
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # Fetch order info safely
        cursor.execute("""
            SELECT id, user_id, owner_user_id, owner_id, helper_id, status, is_direct_booking, price as current_price
            FROM orders
            WHERE id = %s
        """, (order_id,))
        order = cursor.fetchone()

        if not order:
            cursor.close()
            conn.close()
            return jsonify({"success": False, "message": "Order not found."}), 404

        # Determine if this is a direct booking
        is_direct = order.get("is_direct_booking", False)
        
        # For direct bookings, determine who is responding
        if is_direct:
            order_user_id = order.get("user_id")
            order_helper_id = order.get("helper_id")
            
            # Check if current user is the helper or the customer
            if user_id == order_helper_id:
                # Helper is responding
                responder_type = "helper"
                to_user_id = order_user_id
                cursor.execute("SELECT username FROM users WHERE id = %s", (order_user_id,))
                to_user = cursor.fetchone()
                to_username = to_user["username"] if to_user else "User"
            elif user_id == order_user_id:
                # Customer is responding (to a counter offer)
                responder_type = "customer"
                to_user_id = order_helper_id
                cursor.execute("SELECT username FROM users WHERE id = %s", (order_helper_id,))
                to_user = cursor.fetchone()
                to_username = to_user["username"] if to_user else "Helper"
            else:
                cursor.close()
                conn.close()
                return jsonify({"success": False, "message": "You are not authorized to respond to this order."}), 403
        else:
            # Legacy order flow
            to_user_id = order.get("user_id") or order.get("owner_user_id") or order.get("owner_id")
            if not to_user_id:
                cursor.close()
                conn.close()
                return jsonify({"success": False, "message": "Could not determine customer ID."}), 400
            responder_type = "helper"
            cursor.execute("SELECT username FROM users WHERE id = %s", (to_user_id,))
            to_user = cursor.fetchone()
            to_username = to_user["username"] if to_user else "User"

        # --- 3️⃣ Handle Action ---
        if action == "accept":
            if is_direct and order.get("status") not in ["pending", "counter"]:
                cursor.close()
                conn.close()
                return jsonify({"success": False, "message": "Order is not in a negotiable state."}), 400
            
            cursor.execute("""
                UPDATE orders
                SET status = 'accepted', helper_id = %s
                WHERE id = %s
            """, (order.get("helper_id") or user_id, order_id))
            
            if responder_type == "helper":
                message = f"✅ {username} accepted your booking offer."
            else:
                message = f"✅ {username} accepted your counter offer."
                
            # Store in negotiation history
            cursor.execute("""
                INSERT INTO order_negotiations (order_id, sender_id, receiver_id, price, action, message)
                VALUES (%s, %s, %s, %s, 'accept', 'Order accepted')
            """, (order_id, user_id, to_user_id, order.get("current_price")))

        elif action == "reject":
            cursor.execute("""
                UPDATE orders
                SET status = 'rejected'
                WHERE id = %s
            """, (order_id,))
            
            if responder_type == "helper":
                message = f"❌ {username} rejected your booking request."
            else:
                message = f"❌ {username} rejected your counter offer."
            
            # Store in negotiation history
            cursor.execute("""
                INSERT INTO order_negotiations (order_id, sender_id, receiver_id, price, action, message)
                VALUES (%s, %s, %s, %s, 'reject', 'Order rejected')
            """, (order_id, user_id, to_user_id, order.get("current_price")))

        elif action == "counter":
            if not price:
                cursor.close()
                conn.close()
                return jsonify({"success": False, "message": "Price required for counter offer."}), 400
            
            try:
                price = float(price)
                if price <= 0:
                    cursor.close()
                    conn.close()
                    return jsonify({"success": False, "message": "Price must be greater than 0."}), 400
            except ValueError:
                cursor.close()
                conn.close()
                return jsonify({"success": False, "message": "Invalid price format."}), 400
            
            # Update order with new price and set status to counter
            cursor.execute("""
                UPDATE orders
                SET price = %s, status = 'counter'
                WHERE id = %s
            """, (price, order_id))
            
            if responder_type == "helper":
                message = f"💬 {username} requested another price: ₹{price}"
            else:
                message = f"💬 {username} counter-offered with price: ₹{price}"
            
            # Store in negotiation history
            cursor.execute("""
                INSERT INTO order_negotiations (order_id, sender_id, receiver_id, price, action, message)
                VALUES (%s, %s, %s, %s, 'counter', %s)
            """, (order_id, user_id, to_user_id, price, f"Counter offer: ₹{price}"))

        else:
            cursor.close()
            conn.close()
            return jsonify({"success": False, "message": "Invalid action."}), 400

        # --- 4️⃣ Ensure schema and Insert Notification ---
        ensure_notifications_schema()
        cursor.execute("""
            INSERT INTO notifications (from_user_id, to_user_id, order_id, message, type, created_at, is_read)
            VALUES (%s, %s, %s, %s, 'booking_response', NOW(), FALSE)
        """, (user_id, to_user_id, order_id, message))

        conn.commit()
        cursor.close()
        conn.close()

        return jsonify({"success": True, "message": "Action completed successfully."})

    except Exception as e:
        import traceback
        print("Error in /helper_response:", e)
        traceback.print_exc()
        return jsonify({"success": False, "message": "Server error."}), 500

@app.route('/user_response/<int:order_id>', methods=['POST'])
@login_required
def user_response(order_id):
    """User responds to helper's counter offer (Accept / Reject)"""
    data = request.get_json()
    action = data.get('action')

    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Fetch order info
        cursor.execute("SELECT owner_id, helper_id FROM orders WHERE id = %s", (order_id,))
        order = cursor.fetchone()
        if not order:
            return jsonify({'success': False, 'message': 'Order not found'}), 404

        cursor.execute("SELECT id FROM users WHERE username = %s", (session['username'],))
        user_row = cursor.fetchone()
        if not user_row or order['owner_id'] != user_row['id']:
            return jsonify({'success': False, 'message': 'Unauthorized'}), 403

        helper_id = order['helper_id']
        owner_id = order['owner_id']

        if action == 'accept':
            cursor.execute("UPDATE orders SET status = 'accepted' WHERE id = %s", (order_id,))
            msg = f"✅ {session['username']} accepted your offer!"
        elif action == 'reject':
            cursor.execute("UPDATE orders SET status = 'rejected' WHERE id = %s", (order_id,))
            msg = f"❌ {session['username']} rejected your offer."
        else:
            return jsonify({'success': False, 'message': 'Invalid action'}), 400

        # Notify helper
        cursor.execute("""
            INSERT INTO notifications (to_user_id, from_user_id, order_id, message, created_at, is_read)
            VALUES (%s, %s, %s, %s, NOW(), FALSE)
        """, (helper_id, owner_id, order_id, msg))

        # Push notification
        cursor.execute("SELECT fcm_token FROM users WHERE id = %s", (helper_id,))
        token = cursor.fetchone()
        if token and token.get('fcm_token'):
            send_push_notification(token['fcm_token'], "Booking Response", msg)

        conn.commit()
        cursor.close()

    return jsonify({'success': True, 'message': f'Order {action}ed successfully!'})

# ---------------------------
# Admin: Orders Overview
# ---------------------------
@app.route('/admin/orders')
def admin_orders():
    if 'username' not in session or session['username'] != 'adime':
        flash('Admin access required', 'error')
        return redirect(url_for('home'))

    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT 
                o.id AS order_id,
                o.created_at AS order_created_at,
                (SELECT username FROM users WHERE id = o.owner_id) AS owner_username,
                s.service_name,
                l.location_name,
                -- accepted helper from order_requests if present
                (
                  SELECT r.helper_username 
                  FROM order_requests r 
                  WHERE r.order_id = o.id AND r.status = 'accepted' 
                  ORDER BY r.timestamp DESC LIMIT 1
                ) AS accepted_helper,
                (
                  SELECT r.timestamp 
                  FROM order_requests r 
                  WHERE r.order_id = o.id AND r.status = 'accepted' 
                  ORDER BY r.timestamp DESC LIMIT 1
                ) AS accepted_at,
                -- fallback from order_acceptance
                (
                  SELECT u.username 
                  FROM order_acceptance oa 
                  JOIN users u ON u.id = oa.provider_id 
                  WHERE oa.order_id = o.id AND oa.final_selected = TRUE 
                  ORDER BY oa.id DESC LIMIT 1
                ) AS accepted_helper_fallback
            FROM orders o
            JOIN services s ON s.id = o.service_id
            JOIN locations l ON l.id = o.location_id
            ORDER BY o.created_at DESC
        """)
        rows = cur.fetchall()

    # Normalize accepted helper
    for r in rows:
        if not r.get('accepted_helper'):
            r['accepted_helper'] = r.get('accepted_helper_fallback')

    return render_template('admin_orders.html', orders=rows)

# ---------------------------
# Admin: Subscriptions Management
# ---------------------------
@app.route('/admin/subscriptions')
def admin_subscriptions():
    if 'username' not in session or session['username'] != 'adime':
        flash('Admin access required', 'error')
        return redirect(url_for('home'))

    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT id, helper_username, category, status, start_date, end_date
            FROM subscriptions
            ORDER BY status DESC, end_date DESC NULLS LAST
        """)
        subs = cur.fetchall()

    return render_template('admin_subscriptions.html', subscriptions=subs)

@app.route('/admin/subscriptions/cancel', methods=['POST'])
def admin_cancel_subscription():
    if 'username' not in session or session['username'] != 'adime':
        return jsonify({'ok': False, 'error': 'Admin access required'}), 403

    helper_username = request.form.get('helper_username') or (request.json or {}).get('helper_username')
    category = request.form.get('category') or (request.json or {}).get('category')
    if not helper_username or not category:
        return jsonify({'ok': False, 'error': 'helper_username and category are required'}), 400

    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Cancel subscription
        cur.execute("""
            UPDATE subscriptions
            SET status = 'cancelled', end_date = CURRENT_DATE
            WHERE helper_username = %s AND category = %s AND status = 'active'
            RETURNING helper_username
        """, (helper_username, category))
        updated = cur.fetchone()

        if not updated:
            conn.commit()
            return jsonify({'ok': False, 'error': 'No active subscription found'}), 404

        # Notify helper
        cur.execute("SELECT id, fcm_token FROM users WHERE username = %s", (helper_username,))
        user = cur.fetchone()
        if user:
            # Resolve admin user id for notifications, fallback to helper id to satisfy NOT NULL
            cur.execute("SELECT id FROM users WHERE username = %s", (session['username'],))
            admin_row = cur.fetchone()
            admin_id = admin_row['id'] if admin_row else user['id']
            cur.execute("""
                INSERT INTO notifications (to_user_id, from_user_id, order_id, message, created_at, is_read)
                VALUES (%s, %s, %s, %s, NOW(), FALSE)
            """, (user['id'], admin_id, None, f"Your subscription for {category} has been cancelled by admin."))

            if user.get('fcm_token'):
                try:
                    send_push_notification(user['fcm_token'], 'Subscription Cancelled', f'Your {category} subscription was cancelled.')
                except Exception:
                    pass

        conn.commit()

    if request.is_json:
        return jsonify({'ok': True})
    flash('Subscription cancelled and helper notified.', 'success')
    return redirect(url_for('admin_subscriptions'))

@app.route('/admin/subscriptions/cancel_all', methods=['POST'])
def admin_cancel_all_subscriptions():
    if 'username' not in session or session['username'] != 'adime':
        return jsonify({'ok': False, 'error': 'Admin access required'}), 403

    helper_username = request.form.get('helper_username') or (request.json or {}).get('helper_username')
    if not helper_username:
        return jsonify({'ok': False, 'error': 'helper_username is required'}), 400

    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Find active subscriptions
        cur.execute("""
            SELECT category FROM subscriptions
            WHERE helper_username = %s AND status = 'active'
        """, (helper_username,))
        active = cur.fetchall()

        if not active:
            conn.commit()
            return jsonify({'ok': False, 'error': 'No active subscriptions found'}), 404

        # Cancel all active
        cur.execute("""
            UPDATE subscriptions
            SET status = 'cancelled', end_date = CURRENT_DATE
            WHERE helper_username = %s AND status = 'active'
        """, (helper_username,))

        # Notify helper once per category
        cur.execute("SELECT id, fcm_token FROM users WHERE username = %s", (helper_username,))
        user = cur.fetchone()
        if user:
            # Resolve admin user id for notifications, fallback to helper id
            cur.execute("SELECT id FROM users WHERE username = %s", (session['username'],))
            admin_row = cur.fetchone()
            admin_id = admin_row['id'] if admin_row else user['id']
            for row in active:
                category = row.get('category')
                cur.execute("""
                    INSERT INTO notifications (to_user_id, from_user_id, order_id, message, created_at, is_read)
                    VALUES (%s, %s, %s, %s, NOW(), FALSE)
                """, (user['id'], admin_id, None, f"Your subscription for {category} has been cancelled by admin."))
            if user.get('fcm_token'):
                try:
                    send_push_notification(user['fcm_token'], 'Subscriptions Cancelled', 'Your active subscriptions were cancelled by admin.')
                except Exception:
                    pass

        conn.commit()

    if request.is_json:
        return jsonify({'ok': True})
    flash('All active subscriptions cancelled and helper notified.', 'success')
    return redirect(url_for('admin_subscriptions'))

@app.route('/products')
def products():
    return render_template('products.html')

@app.route('/order', methods=['GET', 'POST'])
def place_order():
    if request.method == 'POST':
        # Get form data
        service = request.form['service']
        location = request.form['location']
        message = request.form.get('message', 'No message provided')
        priority = request.form.get('priority', 'normal')
        preferred_date = request.form.get('preferred_date', '')
        preferred_time = request.form.get('preferred_time', '')
        phone = request.form.get('phone', '')
        call_time = request.form.get('call_time', 'anytime')
        image = request.files.get('image')

        # Save image if provided
        image_path = None
        if image and image.filename:
            if not allowed_file(image.filename):
                flash("Invalid file type. Please upload PNG, JPG, JPEG, or GIF files only.", "error")
                return redirect(url_for('place_order'))
            
            if not validate_file_size(image):
                flash("File too large. Please upload images smaller than 10MB.", "error")
                return redirect(url_for('place_order'))
            
            try:
                image_path = upload_to_cloudinary(image)
            except Exception as e:
                print(f"Image upload error: {e}")
                flash("Failed to upload image. Please try again with a smaller file.", "error")
                return redirect(url_for('place_order'))

        conn = get_db_connection()
        cur = conn.cursor()

        try:
            # Lookup IDs
            cur.execute("SELECT id FROM services WHERE service_name = %s", (service,))
            service_result = cur.fetchone()
            if not service_result:
                flash("Service not found. Please try again.", "error")
                return redirect(url_for('place_order'))
            service_id = service_result[0]

            cur.execute("SELECT id FROM locations WHERE location_name = %s", (location,))
            location_result = cur.fetchone()
            if not location_result:
                flash("Location not found. Please try again.", "error")
                return redirect(url_for('place_order'))
            location_id = location_result[0]

            cur.execute("SELECT id FROM users WHERE username = %s", (session['username'],))
            owner_result = cur.fetchone()
            if not owner_result:
                flash("User not found. Please login again.", "error")
                return redirect(url_for('login'))
            owner_id = owner_result[0]

            # Create enhanced message with additional details
            enhanced_message = message
            if preferred_date or preferred_time:
                enhanced_message += f"\n\nPreferred timing: "
                if preferred_date:
                    enhanced_message += f"{preferred_date.replace('_', ' ').title()}"
                if preferred_time:
                    enhanced_message += f" - {preferred_time.replace('_', ' ').title()}"
            
            if phone:
                enhanced_message += f"\nContact: {phone}"
                if call_time != 'anytime':
                    enhanced_message += f" (Best time to call: {call_time.replace('_', ' ').title()})"

            # Insert order with basic data (enhanced message includes all details)
            cur.execute(""" 
                INSERT INTO orders (owner_id, service_id, location_id, message, image_path, created_at)
                VALUES (%s, %s, %s, %s, %s, NOW())
                RETURNING id
            """, (owner_id, service_id, location_id, enhanced_message, image_path))
            order_id = cur.fetchone()[0]

            # Notify providers in that location with matching service type
            # Only notify providers with active subscriptions
            cur.execute(""" 
                SELECT u.id, u.fcm_token, u.username
                FROM users u
                WHERE u.business_type = %s 
                    AND u.location = %s 
                    AND u.account_type = 'business'
            """, (service, location))

            providers_notified = 0
            for provider_id, token, provider_username in cur.fetchall():
                # Check if provider has active subscription - STRICT CHECK: Only subscribed helpers get notifications
                cur.execute("""
                    SELECT 1 FROM subscriptions 
                    WHERE helper_username = %s 
                        AND category = %s 
                        AND status = 'active' 
                        AND end_date >= CURRENT_DATE
                """, (provider_username, service))
                
                has_active_subscription = cur.fetchone()
                
                # Skip if no active subscription - they won't get notified
                if not has_active_subscription:
                    continue
                
                link = url_for('order_request', order_id=order_id)
                
                # Create priority-specific notification message
                priority_emoji = {"emergency": "🚨", "urgent": "⚡", "normal": "📋"}
                notification_message = f"{priority_emoji.get(priority, '📋')} New {priority.title()} Order: {message[:50]}..."
                
                cur.execute(""" 
                    INSERT INTO notifications (to_user_id, from_user_id, order_id, message, link, created_at, is_read)
                    VALUES (%s, %s, %s, %s, %s, NOW(), false)
                """, (provider_id, owner_id, order_id, notification_message, link))

                if token:
                    push_title = f"New {priority.title()} Order"
                    push_body = f"{service} order from {session['username']} in {location}"
                    if priority == 'emergency':
                        push_title = "🚨 Emergency Order"
                        push_body = f"URGENT: {service} needed in {location}"
                    
                    send_push_notification(token, push_title, push_body)
                
                providers_notified += 1

            conn.commit()
            
            # Success message with details
            success_message = f"Order placed successfully! {providers_notified} service providers have been notified."
            if priority == 'emergency':
                success_message += " Due to emergency priority, providers will respond quickly."
            elif priority == 'urgent':
                success_message += " Due to urgent priority, expect faster response times."
            
            flash(success_message, "success")
            return redirect(url_for('home'))

        except Exception as e:
            conn.rollback()
            print(f"Error placing order: {e}")
            flash("An error occurred while placing your order. Please try again.", "error")
            return redirect(url_for('place_order'))
        finally:
            cur.close()
            conn.close()

    # GET form - Enhanced with service descriptions
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    # Get services (without description column for now)
    cur.execute("SELECT service_name FROM services ORDER BY service_name")
    services = cur.fetchall()
    
    # Get locations
    cur.execute("SELECT location_name FROM locations ORDER BY location_name")
    locations = cur.fetchall()
    
    cur.close()
    conn.close()
    return render_template('order.html', services=services, locations=locations)


@app.route('/approve_provider/<int:order_id>', methods=['POST'])
def approve_provider(order_id):
    selected_provider_id = request.form.get('selected_provider_id')
    if not selected_provider_id:
        flash("No provider selected.")
        return redirect('/notifications')

    conn = get_db_connection()
    cur = conn.cursor()

    # Approve selected provider
    cur.execute("""
        UPDATE order_acceptance SET final_selected = TRUE 
        WHERE order_id = %s AND provider_id = %s
    """, (order_id, selected_provider_id))

    # Reject others
    cur.execute("""
        UPDATE order_acceptance SET accepted = FALSE 
        WHERE order_id = %s AND provider_id != %s
    """, (order_id, selected_provider_id))

    # Get owner_id
    cur.execute("SELECT owner_id FROM orders WHERE id = %s", (order_id,))
    owner_id = cur.fetchone()[0]

    # Notify approved provider
    cur.execute(""" 
        INSERT INTO notifications (to_user_id, from_user_id, order_id, message, created_at, is_read)
        VALUES (%s, %s, %s, %s, NOW(), FALSE)
    """, (selected_provider_id, owner_id, order_id, f"Owner has accepted your request for Order #{order_id}!"))

    cur.execute("SELECT fcm_token FROM users WHERE id = %s", (selected_provider_id,))
    token = cur.fetchone()[0]
    if token:
        send_push_notification(token, "Request Accepted", f"Owner has accepted your request for Order #{order_id}!")

    # Notify rejected providers
    cur.execute("""
        SELECT provider_id FROM order_acceptance 
        WHERE order_id = %s AND provider_id != %s
    """, (order_id, selected_provider_id))
    for (reject_id,) in cur.fetchall():
        cur.execute(""" 
            INSERT INTO notifications (to_user_id, from_user_id, order_id, message, created_at, is_read)
            VALUES (%s, %s, %s, %s, NOW(), FALSE)
        """, (reject_id, owner_id, order_id, f"You have been rejected by owner for Order #{order_id}."))

    conn.commit()
    cur.close()
    conn.close()
    flash("Provider selection finalized.")
    return redirect('/home')


@app.route('/order_request/<int:order_id>', methods=['POST'])
def order_request(order_id):
    conn = get_db_connection()
    cur = conn.cursor()

    # Get provider ID
    cur.execute("SELECT id FROM users WHERE username = %s", (session['username'],))
    provider_id = cur.fetchone()[0]

    # Check if already requested
    cur.execute("""
        SELECT id FROM order_acceptance 
        WHERE order_id = %s AND provider_id = %s
    """, (order_id, provider_id))
    
    if cur.fetchone():
        flash("You have already requested this order!", "info")
        return redirect(url_for('notifications'))

    # Insert request (not accepted yet)
    cur.execute("""
        INSERT INTO order_acceptance (order_id, provider_id, accepted)
        VALUES (%s, %s, FALSE)
    """, (order_id, provider_id))

    # Get owner_id
    cur.execute("SELECT owner_id FROM orders WHERE id = %s", (order_id,))
    owner_id = cur.fetchone()[0]

    # Notify owner about the request
    cur.execute(""" 
        INSERT INTO notifications (to_user_id, from_user_id, order_id, message, created_at, is_read)
        VALUES (%s, %s, %s, %s, NOW(), FALSE)
    """, (owner_id, provider_id, order_id, f"{session['username']} has requested your order!"))

    cur.execute("SELECT fcm_token FROM users WHERE id = %s", (owner_id,))
    token = cur.fetchone()[0]
    if token:
        send_push_notification(token, "Order Request", f"{session['username']} has requested your order!")

    conn.commit()
    cur.close()
    conn.close()
    flash("Your request has been sent to the order owner!")
    return redirect(url_for('notifications'))

# New route for requesting orders with amount
@app.route('/request_order_with_amount/<int:order_id>', methods=['POST'])
@login_required
def request_order_with_amount(order_id):
    """Handle order request with amount from helper"""
    if 'username' not in session:
        return jsonify({'success': False, 'message': 'Not logged in'}), 401

    data = request.get_json()
    amount = data.get('amount')

    if not amount or float(amount) <= 0:
        return jsonify({'success': False, 'message': 'Please enter a valid amount'}), 400

    helper_username = session['username']

    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Verify user is a helper
        cur.execute("SELECT id, account_type FROM users WHERE username = %s", (helper_username,))
        user = cur.fetchone()
        if not user or user['account_type'] != 'business':
            return jsonify({'success': False, 'message': 'Only helpers can request orders'}), 403

        helper_id = user['id']

        # Check if already requested this order
        cur.execute("SELECT id FROM order_requests WHERE order_id = %s AND helper_username = %s", (order_id, helper_username))
        if cur.fetchone():
            return jsonify({'success': False, 'message': 'You have already submitted an offer for this order'}), 400

        # Get order owner for both legacy (owner_id) and direct (user_id)
        cur.execute("""
            SELECT COALESCE(user_id, owner_id) AS owner_id
            FROM orders
            WHERE id = %s
        """, (order_id,))
        order_result = cur.fetchone()
        if not order_result or not order_result['owner_id']:
            return jsonify({'success': False, 'message': 'Order not found'}), 404

        owner_id = order_result['owner_id']

        # Insert order request with amount
        cur.execute("""
            INSERT INTO order_requests (order_id, helper_username, amount, status)
            VALUES (%s, %s, %s, 'pending')
        """, (order_id, helper_username, amount))

        # Ensure a corresponding row exists in order_acceptance
        cur.execute("""
            SELECT 1 FROM order_acceptance WHERE order_id = %s AND provider_id = %s
        """, (order_id, helper_id))
        if not cur.fetchone():
            cur.execute("""
                INSERT INTO order_acceptance (order_id, provider_id, accepted)
                VALUES (%s, %s, FALSE)
            """, (order_id, helper_id))

        # Create notification for the user (order owner) with link to view offers
        ensure_notifications_schema()
        message = f"{helper_username} submitted an offer of ₹{amount} for your order"
        offer_link = url_for('view_offers', order_id=order_id)
        try:
            cur.execute("""
                INSERT INTO notifications (to_user_id, from_user_id, order_id, message, link, type, created_at, is_read)
                VALUES (%s, %s, %s, %s, %s, %s, NOW(), FALSE)
            """, (owner_id, helper_id, order_id, message, offer_link, 'offer_received'))
        except Exception:
            # Fallback if link/type columns are missing
            cur.execute("""
                INSERT INTO notifications (to_user_id, from_user_id, order_id, message, created_at, is_read)
                VALUES (%s, %s, %s, %s, NOW(), FALSE)
            """, (owner_id, helper_id, order_id, message))

        # Send push notification if available
        cur.execute("SELECT fcm_token FROM users WHERE id = %s", (owner_id,))
        token_result = cur.fetchone()
        if token_result and token_result.get('fcm_token'):
            try:
                send_push_notification(
                    token_result['fcm_token'],
                    "New Offer Received",
                    f"{helper_username} offered ₹{amount} for your order"
                )
            except Exception:
                pass

        conn.commit()

    return jsonify({'success': True, 'message': 'Your offer has been sent successfully!'})

@app.route('/notifications')
def notifications():
    if 'username' not in session:
        return redirect('/login')

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # Updated query (adds o.status and o.is_direct_booking, handles direct bookings)
    cur.execute("""SELECT 
    n.id, 
    u_from.username AS from_user, 
    u_from.id AS from_user_id,
    u_to.username AS to_user, 
    n.order_id, 
    COALESCE(s.service_name, 
        (SELECT business_type FROM users WHERE id = o.helper_id)) AS service_name, 
    COALESCE(l.location_name,
        (SELECT location FROM users WHERE id = o.helper_id)) AS location_name, 
    COALESCE(o.message, o.about) AS order_message, 
    o.created_at AS order_created_at, 
    n.message, 
    n.created_at AS notif_created_at, 
    n.is_read,
    COALESCE(o.is_direct_booking, FALSE) AS is_direct_booking,
    o.status AS order_status,
    o.price AS order_price,
    o.about AS order_about,
    o.image_url AS order_image_url,
    (
        SELECT r.helper_username
        FROM order_requests r
        WHERE r.order_id = n.order_id AND r.status = 'accepted'
        LIMIT 1
    ) AS approved_provider,
    COALESCE(
        (SELECT username FROM users WHERE id = o.owner_id),
        (SELECT username FROM users WHERE id = o.user_id)
    ) AS owner_username,
    COALESCE(
        (SELECT phone FROM users WHERE id = o.owner_id),
        (SELECT phone FROM users WHERE id = o.user_id)
    ) AS owner_phone,
    (
        SELECT username FROM users WHERE id = o.helper_id
    ) AS helper_username,
    (
        SELECT username FROM users WHERE id = o.user_id
    ) AS user_username,
    (
        SELECT COUNT(*) FROM order_requests
        WHERE order_id = n.order_id AND helper_username = %s
    ) AS has_requested

    FROM notifications n
    JOIN users u_from ON u_from.id = n.from_user_id
    JOIN users u_to   ON u_to.id   = n.to_user_id
    JOIN orders o     ON o.id = n.order_id
    LEFT JOIN services s   ON s.id = o.service_id
    LEFT JOIN locations l  ON l.id = o.location_id
    WHERE n.to_user_id = (
        SELECT id FROM users WHERE username = %s
    )
    ORDER BY n.id DESC
    """, (session['username'], session['username'],))

    notes = cur.fetchall()
    
    # Check if current user is a helper and has active subscription
    cur.execute("""
        SELECT account_type, business_type FROM users WHERE username = %s
    """, (session['username'],))
    user_info = cur.fetchone()
    
    has_active_subscription = False
    subscription_plan_exists = False
    business_type = None
    
    if user_info and user_info['account_type'] == 'business':
        business_type = user_info['business_type']
        
        # Check if subscription plan exists for this category
        cur.execute("SELECT 1 FROM subscription_plans WHERE category = %s", (business_type,))
        subscription_plan_exists = cur.fetchone() is not None
        
        # Check if user has active subscription
        if subscription_plan_exists:
            cur.execute("""
                SELECT 1 FROM subscriptions 
                WHERE helper_username = %s 
                    AND category = %s 
                    AND status = 'active' 
                    AND end_date >= CURRENT_DATE
            """, (session['username'], business_type))
            has_active_subscription = cur.fetchone() is not None
    
    cur.close()
    conn.close()
    return render_template('notification.html', 
                         notifications=notes, 
                         has_active_subscription=has_active_subscription,
                         subscription_plan_exists=subscription_plan_exists,
                         business_type=business_type)


@app.route('/api/notifications')
def api_notifications():
    if 'username' not in session:
        return jsonify([])

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # Same logic for API version
    cur.execute("""SELECT 
    n.id, 
    u_from.username AS from_user, 
    u_from.id AS from_user_id,
    u_to.username AS to_user, 
    n.order_id, 
    s.service_name, 
    l.location_name, 
    o.message AS order_message, 
    o.created_at AS order_created_at, 
    n.message, 
    n.created_at AS notif_created_at, 
    n.is_read,
    o.is_direct_booking,
    o.status AS order_status,
    (
        SELECT r.helper_username
        FROM order_requests r
        WHERE r.order_id = n.order_id AND r.status = 'accepted'
        LIMIT 1
    ) AS approved_provider,
    (
        SELECT username FROM users WHERE id = o.owner_id
    ) AS owner_username,
    (
        SELECT phone FROM users WHERE id = o.owner_id
    ) AS owner_phone,
    (
        SELECT COUNT(*) FROM order_requests
        WHERE order_id = n.order_id AND helper_username = %s
    ) AS has_requested

    FROM notifications n
    JOIN users u_from ON u_from.id = n.from_user_id
    JOIN users u_to   ON u_to.id   = n.to_user_id
    JOIN orders o     ON o.id = n.order_id
    JOIN services s   ON s.id = o.service_id
    JOIN locations l  ON l.id = o.location_id
    WHERE n.to_user_id = (
        SELECT id FROM users WHERE username = %s
    )
    ORDER BY n.id DESC
    """, (session['username'], session['username'],))

    rows = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify(rows)

@app.route('/api/unread_count')
def api_unread_count():
    if 'username' not in session:
        return jsonify({'count': 0})

    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT COUNT(*)
            FROM notifications n
            WHERE n.is_read = FALSE AND n.to_user_id = (
                SELECT id FROM users WHERE username = %s
            )
        """, (session['username'],))
        count = cur.fetchone()[0]
    return jsonify({'count': count})

@app.route('/api/mark_read', methods=['POST'])
def api_mark_read():
    if 'username' not in session:
        return jsonify({'ok': False, 'error': 'Not logged in'}), 401

    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            UPDATE notifications
            SET is_read = TRUE
            WHERE to_user_id = (SELECT id FROM users WHERE username = %s)
              AND is_read = FALSE
        """, (session['username'],))
        conn.commit()
    return jsonify({'ok': True})

@app.route('/save-token', methods=['POST'])
def save_token():
    """Save Firebase token for push notifications"""
    if 'username' not in session:
        return jsonify({'error': 'Not logged in'}), 401

    data = request.get_json()
    token = data.get('token')
    if not token:
        return jsonify({'error': 'Token is required'}), 400

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET fcm_token = %s WHERE username = %s", (token, session['username']))
        conn.commit()

    return jsonify({'message': 'Token registered successfully'}), 200

@app.route('/report/<username>', methods=['GET', 'POST'])
def report(username):
    if 'username' not in session:
        return redirect(url_for('login'))

    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Get IDs for both users
        cursor.execute("SELECT id, username FROM users WHERE username = %s", (username,))
        to_user = cursor.fetchone()

        cursor.execute("SELECT id, username FROM users WHERE username = %s", (session['username'],))
        from_user = cursor.fetchone()

        if not to_user or not from_user:
            flash("User not found.")
            return redirect(url_for('profile', username=username))

        if request.method == 'POST':
            reason = request.form['reason']

            cursor.execute("""
                INSERT INTO reports (reported_user, reported_by, reason, reported_user_id, reported_by_id)
                VALUES (%s, %s, %s, %s, %s)
            """, (
                to_user['username'],   # old column
                from_user['username'], # old column
                reason,
                to_user['id'],         # new ID column
                from_user['id']        # new ID column
            ))
            conn.commit()

            flash('Report submitted successfully!', 'success')
            return redirect(url_for('profile', username=username))

    return render_template('report.html', username=username)

@app.route('/suggest', methods=['GET'])
def suggest():
    term = request.args.get('term', '')
    suggestions = []

    if term:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Get services
        cursor.execute("SELECT service_name FROM services WHERE service_name ILIKE %s LIMIT 5", (f'%{term}%',))
        services = cursor.fetchall()

        # Get business usernames only
        cursor.execute("SELECT username FROM users WHERE account_type = 'business' AND username ILIKE %s LIMIT 5", (f'%{term}%',))
        businesses = cursor.fetchall()

        # Get locations
        cursor.execute("SELECT location_name FROM locations WHERE location_name ILIKE %s LIMIT 5", (f'%{term}%',))
        locations = cursor.fetchall()

        conn.close()

        # Add them to suggestions
        suggestions.extend(service[0] for service in services)
        suggestions.extend(business[0] for business in businesses)
        suggestions.extend(location[0] for location in locations)

    return jsonify(suggestions)

@app.route('/api/helper_by_code')
def api_helper_by_code():
    """Lookup helper(s) by a scanned code value. The QR code is expected to
    contain either a 10-digit helperid or a username. Returns a lightweight
    profile list so the UI can render inline without navigation.
    """
    code = request.args.get('code', '').strip()
    if not code:
        return jsonify({"helpers": []})

    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        results = []
        try:
            # Try direct numeric helperid
            if code.isdigit() and len(code) in (6, 8, 10, 12):
                # Treat numeric codes of common lengths as helperid
                cur.execute("""
                    SELECT username, business_type, location, profile_pic, price, phone,
                           COALESCE(AVG(f.rating), 0) AS avg_rating
                    FROM users u
                    LEFT JOIN feedback f ON u.id = f.to_user_id
                    WHERE u.account_type = 'business' AND u.helperid = %s
                    GROUP BY username, business_type, location, profile_pic, price, phone
                """, (code,))
                results = cur.fetchall()
            else:
                # If the code is a URL or text, try to extract helperid or username heuristically
                from urllib.parse import urlparse, parse_qs
                extracted_helperid = None
                extracted_username = None
                try:
                    parsed = urlparse(code)
                    if parsed.scheme in ('http', 'https', 'mrhelper'):
                        qs = parse_qs(parsed.query or '')
                        if 'helperid' in qs and qs['helperid']:
                            extracted_helperid = qs['helperid'][0]
                        if 'username' in qs and qs['username']:
                            extracted_username = qs['username'][0]
                        # Also try last path segment as username or id
                        if not extracted_username and parsed.path:
                            seg = parsed.path.rstrip('/').split('/')[-1]
                            if seg:
                                if seg.isdigit():
                                    extracted_helperid = seg
                                else:
                                    extracted_username = seg
                except Exception:
                    pass

                # If still nothing, try to pick first 10-12 digit sequence from free text
                if not extracted_helperid:
                    import re
                    match = re.search(r"(\d{6,12})", code)
                    if match:
                        extracted_helperid = match.group(1)

                # Query in priority: helperid then username then exact text username
                if extracted_helperid:
                    cur.execute("""
                        SELECT username, business_type, location, profile_pic, price, phone,
                               COALESCE(AVG(f.rating), 0) AS avg_rating
                        FROM users u
                        LEFT JOIN feedback f ON u.id = f.to_user_id
                        WHERE u.account_type = 'business' AND u.helperid = %s
                        GROUP BY username, business_type, location, profile_pic, price, phone
                    """, (extracted_helperid,))
                    results = cur.fetchall()

                if not results and extracted_username:
                    cur.execute("""
                        SELECT username, business_type, location, profile_pic, price, phone,
                               COALESCE(AVG(f.rating), 0) AS avg_rating
                        FROM users u
                        LEFT JOIN feedback f ON u.id = f.to_user_id
                        WHERE u.account_type = 'business' AND u.username = %s
                        GROUP BY username, business_type, location, profile_pic, price, phone
                    """, (extracted_username,))
                    results = cur.fetchall()

                if not results:
                    cur.execute("""
                        SELECT username, business_type, location, profile_pic, price, phone,
                               COALESCE(AVG(f.rating), 0) AS avg_rating
                        FROM users u
                        LEFT JOIN feedback f ON u.id = f.to_user_id
                        WHERE u.account_type = 'business' AND u.username = %s
                        GROUP BY username, business_type, location, profile_pic, price, phone
                    """, (code,))
                    results = cur.fetchall()
        except Exception as e:
            print('api_helper_by_code error:', e)
            results = []

    return jsonify({"helpers": results})

# Expose Firebase messaging service worker at root path for FCM compatibility
@app.route('/firebase-messaging-sw.js')
def firebase_messaging_sw():
    return send_from_directory('static', 'firebase-messaging-sw.js')

@app.route('/service/<service_name>')
def service(service_name):
    # Backward compatibility: redirect old route to the new service browser
    return redirect(url_for('service_by_business', business_type=service_name))

# New service browsing by business type with service types and helper profiles
@app.route('/service/by/<business_type>')
def service_by_business(business_type):
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Service types for the selected business type
        try:
            cursor.execute(
                """
                SELECT st.id, st.name, st.icon
                FROM service_types st
                JOIN business_types bt ON bt.id = st.business_type_id
                WHERE LOWER(bt.name) = LOWER(%s)
                ORDER BY st.name
                """,
                (business_type,)
            )
            service_types = cursor.fetchall()
        except Exception:
            # Fallback if service_types table not present
            service_types = []

        # Fallback: derive service types from users if none found
        if not service_types:
            cursor.execute(
                """
                SELECT DISTINCT NULL::int as id, COALESCE(service_type,'') as name, NULL::text as icon
                FROM users
                WHERE account_type='business' AND LOWER(business_type)=LOWER(%s) AND COALESCE(service_type,'') <> ''
                ORDER BY name
                """,
                (business_type,)
            )
            service_types = cursor.fetchall()

        # Helpers under this business type (sorted highest rating first) - compute avg from feedback
        cursor.execute(
            """
            SELECT 
              u.username,
              u.business_type,
              u.service_type,
              u.location,
              COALESCE(AVG(f.rating), 0) AS avg_rating,
              u.profile_pic,
              u.price_numeric AS price
            FROM users u
            LEFT JOIN feedback f ON u.id = f.to_user_id
            WHERE u.account_type='business' AND LOWER(u.business_type) = LOWER(%s)
            GROUP BY u.username, u.business_type, u.service_type, u.location, u.profile_pic, u.price_numeric
            ORDER BY COALESCE(AVG(f.rating), 0) DESC
            """,
            (business_type,)
        )
        helpers = cursor.fetchall()

        # Distinct locations for filters
        cursor.execute(
            """
            SELECT DISTINCT location
            FROM users
            WHERE account_type='business' AND LOWER(business_type) = LOWER(%s)
                  AND location IS NOT NULL AND location <> ''
            ORDER BY location
            """,
            (business_type,)
        )
        locations = [r['location'] for r in cursor.fetchall()]

    return render_template(
        'service.html',
        business_type=business_type,
        service_types=service_types,
        helpers=helpers,
        locations=locations
    )

# AJAX filter endpoint for helper profiles
@app.route('/filter_helpers', methods=['POST'])
def filter_helpers():
    data = request.get_json(silent=True) or request.form
    business_type = (data.get('business_type') or '').strip()
    service_type = (data.get('service_type') or '').strip()
    location = (data.get('location') or '').strip()
    min_rating = data.get('min_rating')
    price_min = data.get('price_min')
    price_max = data.get('price_max')
    search = (data.get('search') or '').strip()

    clauses = ["account_type='business'"]
    params = []

    if business_type:
        clauses.append("LOWER(business_type) = LOWER(%s)")
        params.append(business_type)
    if service_type:
        # Allow match either by exact name or id passed as string int
        try:
            _ = int(service_type)
            clauses.append("service_type_id = %s")
            params.append(int(service_type))
        except Exception:
            clauses.append("LOWER(service_type) = LOWER(%s)")
            params.append(service_type)
    if location:
        clauses.append("LOWER(location) = LOWER(%s)")
        params.append(location)
    if min_rating not in (None, "", []):
        try:
            clauses.append("COALESCE(avg_rating, 0) >= %s")
            params.append(float(min_rating))
        except Exception:
            pass
    if price_min not in (None, "", []):
        try:
            clauses.append("COALESCE(price_numeric, 0) >= %s")
            params.append(float(price_min))
        except Exception:
            pass
    if price_max not in (None, "", []):
        try:
            clauses.append("COALESCE(price_numeric, 0) <= %s")
            params.append(float(price_max))
        except Exception:
            pass
    if search:
        clauses.append("(username ILIKE %s OR COALESCE(bio,'') ILIKE %s)")
        params.extend([f"%{search}%", f"%{search}%"])

    where_sql = " AND ".join(clauses) if clauses else "TRUE"

    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        base_sql = f"""
            SELECT 
              u.username,
              u.business_type,
              u.service_type,
              u.location,
              COALESCE(AVG(f.rating), 0) AS avg_rating,
              u.profile_pic,
              u.price_numeric AS price
            FROM users u
            LEFT JOIN feedback f ON u.id = f.to_user_id
            WHERE {where_sql}
            GROUP BY u.username, u.business_type, u.service_type, u.location, u.profile_pic, u.price_numeric
        """

        # Apply HAVING for min_rating if provided
        having_clause = ""
        having_params = []
        if min_rating not in (None, "", []):
            try:
                having_clause = " HAVING COALESCE(AVG(f.rating), 0) >= %s"
                having_params.append(float(min_rating))
            except Exception:
                pass

        order_limit = " ORDER BY COALESCE(AVG(f.rating), 0) DESC LIMIT 200"
        cur.execute(base_sql + having_clause + order_limit, tuple(params + having_params))
        results = cur.fetchall()

    return jsonify({"helpers": results})

@app.route('/rate_comment/<username>', methods=['POST'])
def rate_comment(username):
    if 'username' not in session:
        return redirect(url_for('login'))

    rating = int(request.form['rating'])
    comment = request.form['comment']

    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Get IDs for both users
        cur.execute("SELECT id FROM users WHERE username = %s", (username,))
        to_user = cur.fetchone()
        if not to_user:
            flash("User not found.")
            return redirect(url_for('profile', username=username))

        cur.execute("SELECT id FROM users WHERE username = %s", (session['username'],))
        from_user = cur.fetchone()
        if not from_user:
            flash("Session error: logged-in user not found.")
            return redirect(url_for('profile', username=username))

        # Prevent multiple ratings
        cur.execute("""
            SELECT 1 FROM feedback 
            WHERE to_user_id = %s AND from_user_id = %s
        """, (to_user['id'], from_user['id']))
        if cur.fetchone():
            flash("You have already rated this user.")
            return redirect(url_for('profile', username=username))

        # Insert feedback
        cur.execute("""
            INSERT INTO feedback (to_user_id, from_user_id, rating, comment)
            VALUES (%s, %s, %s, %s)
        """, (to_user['id'], from_user['id'], rating, comment))

        conn.commit()

    flash("Rating submitted successfully.")
    return redirect(url_for('profile', username=username))
@app.route('/delete_rating/<username>', methods=['POST'])
def delete_rating(username):
    if 'username' not in session:
        return redirect(url_for('login'))

    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Get IDs for both users
        cur.execute("SELECT id FROM users WHERE username = %s", (username,))
        to_user = cur.fetchone()

        cur.execute("SELECT id FROM users WHERE username = %s", (session['username'],))
        from_user = cur.fetchone()

        if to_user and from_user:
            cur.execute("""
                DELETE FROM feedback
                WHERE to_user_id = %s AND from_user_id = %s
            """, (to_user['id'], from_user['id']))
            conn.commit()

    flash("Your rating was deleted.")
    return redirect(url_for('profile', username=username))

# Order tracking and management routes
@app.route('/my_orders')
def my_orders():
    if 'username' not in session:
        return redirect(url_for('login'))

    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        # Get user's orders with basic information
        cur.execute("""
            SELECT 
                o.id,
                o.message,
                o.created_at,
                s.service_name,
                l.location_name,
                (
                    SELECT COUNT(*)
                    FROM order_acceptance oa
                    WHERE oa.order_id = o.id AND oa.accepted = TRUE
                ) as accepted_count,
                (
                    SELECT u_provider.username
                    FROM order_acceptance oa
                    JOIN users u_provider ON u_provider.id = oa.provider_id
                    WHERE oa.order_id = o.id AND oa.final_selected = TRUE
                    LIMIT 1
                ) as selected_provider
            FROM orders o
            JOIN services s ON s.id = o.service_id
            JOIN locations l ON l.id = o.location_id
            WHERE o.owner_id = (
                SELECT id FROM users WHERE username = %s
            )
            ORDER BY o.created_at DESC
        """, (session['username'],))
        
        orders = cur.fetchall()
        
        # Add default values for orders (since new columns don't exist yet)
        for order in orders:
            order['priority'] = 'normal'
            order['status'] = 'pending'
            order['budget'] = None
            order['payment_preference'] = 'cash'
            order['tracking'] = []

    return render_template('my_orders.html', orders=orders)

@app.route('/order/<int:order_id>')
def order_details(order_id):
    if 'username' not in session:
        return redirect(url_for('login'))

    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        # Get order details with enhanced information (handles both direct bookings and legacy orders)
        cur.execute("""
            SELECT 
                o.*,
                COALESCE(s.service_name, 
                    (SELECT business_type FROM users WHERE id = o.helper_id)) AS service_name,
                COALESCE(l.location_name,
                    (SELECT location FROM users WHERE id = o.helper_id)) AS location_name,
                COALESCE(
                    u_owner.username,
                    (SELECT username FROM users WHERE id = o.user_id)
                ) as owner_username,
                COALESCE(
                    u_owner.phone,
                    (SELECT phone FROM users WHERE id = o.user_id)
                ) as owner_phone,
                COALESCE(
                    u_owner.gmail,
                    (SELECT gmail FROM users WHERE id = o.user_id)
                ) as owner_email,
                COALESCE(
                    u_owner.location,
                    (SELECT location FROM users WHERE id = o.user_id)
                ) as owner_location,
                oa.final_selected,
                u_provider.username as approved_provider,
                (SELECT username FROM users WHERE id = o.user_id) as user_username,
                (SELECT username FROM users WHERE id = o.helper_id) as helper_username,
                COALESCE(o.is_direct_booking, FALSE) as is_direct_booking
            FROM orders o
            LEFT JOIN services s ON s.id = o.service_id
            LEFT JOIN locations l ON l.id = o.location_id
            LEFT JOIN users u_owner ON u_owner.id = o.owner_id
            LEFT JOIN order_acceptance oa ON oa.order_id = o.id AND oa.final_selected = TRUE
            LEFT JOIN users u_provider ON u_provider.id = oa.provider_id
            WHERE o.id = %s
        """, (order_id,))
        
        order = cur.fetchone()
        if not order:
            flash("Order not found.", "error")
            return redirect(url_for('my_orders'))
        
        # Add default values for missing fields
        order['priority'] = order.get('priority', 'normal')
        order['status'] = order.get('status', 'pending')
        order['budget'] = order.get('budget', None)
        order['payment_preference'] = order.get('payment_preference', 'cash')
        order['phone'] = order.get('phone', None)
        order['preferred_date'] = order.get('preferred_date', None)
        order['preferred_time'] = order.get('preferred_time', None)
        order['call_time'] = order.get('call_time', 'anytime')
        
        # Check if user has access to this order
        cur.execute("SELECT id FROM users WHERE username = %s", (session['username'],))
        current_user = cur.fetchone()
        
        # Check access for direct bookings
        is_direct = order.get('is_direct_booking', False)
        has_access = False
        
        if is_direct:
            # For direct bookings: user_id is customer, helper_id is helper
            user_id = order.get('user_id')
            helper_id = order.get('helper_id')
            if current_user['id'] == user_id or current_user['id'] == helper_id:
                has_access = True
        else:
            # Legacy orders: owner_id is customer
            owner_id = order.get('owner_id')
            if current_user['id'] == owner_id:
                has_access = True
        
        # Also allow access if this user is the accepted helper via order_requests
        cur.execute("""
            SELECT 1 FROM order_requests 
            WHERE order_id = %s AND helper_username = %s AND status = 'accepted'
            LIMIT 1
        """, (order_id, session['username']))
        has_access_via_requests = cur.fetchone() is not None
        
        # User can access if they are the owner, approved provider (either source), or admin
        if (not has_access and
            order.get('approved_provider') != session['username'] and 
            not has_access_via_requests and
            session['username'] != 'adime'):
            flash("You don't have permission to view this order", "error")
            return redirect(url_for('notifications'))
        
        # Get negotiation history for direct bookings
        negotiations = []
        if is_direct:
            cur.execute("""
                SELECT 
                    on_neg.*,
                    u_sender.username as sender_username,
                    u_receiver.username as receiver_username
                FROM order_negotiations on_neg
                JOIN users u_sender ON u_sender.id = on_neg.sender_id
                JOIN users u_receiver ON u_receiver.id = on_neg.receiver_id
                WHERE on_neg.order_id = %s
                ORDER BY on_neg.created_at ASC
            """, (order_id,))
            negotiations = cur.fetchall()
        
        # Get basic order info (tracking not available yet)
        tracking = []
        
        # Get accepted providers with enhanced information
        cur.execute("""
            SELECT 
                oa.*,
                u.username,
                u.phone,
                u.gmail as email,
                u.location,
                u.profile_pic,
                u.avg_rating,
                NOW() as accepted_at
            FROM order_acceptance oa
            JOIN users u ON u.id = oa.provider_id
            WHERE oa.order_id = %s AND oa.accepted = TRUE
            ORDER BY oa.id DESC
        """, (order_id,))
        accepted_providers = cur.fetchall()
        
        # Get verification status and deadline for order
        order['is_verified'] = order.get('is_verified', False)
        order['verification_deadline'] = order.get('verification_deadline')
        order['user_action'] = order.get('user_action')
        order['verification_helper_id'] = order.get('verification_helper_id')

    return render_template('order_details.html', 
                         order=order, 
                         tracking=tracking, 
                         accepted_providers=accepted_providers,
                         negotiations=negotiations)

@app.route('/update_order_status/<int:order_id>', methods=['POST'])
def update_order_status(order_id):
    if 'username' not in session:
        return redirect(url_for('login'))

    new_status = request.form.get('status')
    message = request.form.get('message', '')
    
    if not new_status:
        flash("Status is required.", "error")
        return redirect(url_for('order_details', order_id=order_id))

    with get_db_connection() as conn:
        cur = conn.cursor()
        
        # Get current user ID
        cur.execute("SELECT id FROM users WHERE username = %s", (session['username'],))
        user = cur.fetchone()
        if not user:
            flash("User not found.", "error")
            return redirect(url_for('order_details', order_id=order_id))
        
        user_id = user[0]
        
        # Update order status
        cur.execute("""
            UPDATE orders 
            SET status = %s 
            WHERE id = %s
        """, (new_status, order_id))
        
        # Also update message if provided
        if message:
            cur.execute("""
                UPDATE orders 
                SET message = message || '\n\nStatus Update: ' || %s || ' (Updated by: ' || %s || ' at ' || NOW() || ')'
                WHERE id = %s
            """, (message, session['username'], order_id))
        
        # If order is being cancelled, notify all accepted providers
        if new_status == 'cancelled':
            cur.execute("""
                SELECT oa.provider_id, u.username, u.fcm_token
                FROM order_acceptance oa
                JOIN users u ON u.id = oa.provider_id
                WHERE oa.order_id = %s AND oa.accepted = TRUE
            """, (order_id,))
            
            accepted_providers = cur.fetchall()
            
            for provider_id, provider_username, fcm_token in accepted_providers:
                # Send notification to provider
                cur.execute("""
                    INSERT INTO notifications (to_user_id, from_user_id, order_id, message, created_at, is_read)
                    VALUES (%s, %s, %s, %s, NOW(), FALSE)
                """, (provider_id, user_id, order_id, f"Order #{order_id} has been cancelled by the customer."))
                
                # Send push notification if token exists
                if fcm_token:
                    send_push_notification(
                        fcm_token,
                        "Order Cancelled",
                        f"Order #{order_id} has been cancelled by the customer."
                    )
        
        conn.commit()
        
        # Notify relevant users for other status updates
        if new_status != 'cancelled':
            cur.execute("""
                SELECT owner_id, service_id, location_id
                FROM orders
                WHERE id = %s
            """, (order_id,))
            order_info = cur.fetchone()
            
            if order_info:
                owner_id, service_id, location_id = order_info
                
                # Notify order owner
                if user_id != owner_id:
                    cur.execute("""
                        INSERT INTO notifications (to_user_id, from_user_id, order_id, message, created_at, is_read)
                        VALUES (%s, %s, %s, %s, NOW(), FALSE)
                    """, (owner_id, user_id, order_id, f"Order status updated to: {new_status}"))
                
                # Notify approved provider about status change
                cur.execute("""
                    SELECT u_provider.id, u_provider.fcm_token
                    FROM order_acceptance oa
                    JOIN users u_provider ON u_provider.id = oa.provider_id
                    WHERE oa.order_id = %s AND oa.final_selected = TRUE
                """, (order_id,))
                
                provider_result = cur.fetchone()
                if provider_result:
                    provider_id, fcm_token = provider_result
                    
                    # Create notification
                    status_messages = {
                        'in_progress': f"Order #{order_id} has been marked as in progress",
                        'completed': f"Order #{order_id} has been completed",
                        'pending': f"Order #{order_id} status updated to pending"
                    }
                    
                    notification_message = status_messages.get(new_status, f"Order #{order_id} status updated to {new_status}")
                    
                    cur.execute("""
                        INSERT INTO notifications (to_user_id, from_user_id, order_id, message, created_at, is_read)
                        VALUES (%s, %s, %s, %s, NOW(), FALSE)
                    """, (provider_id, user_id, order_id, notification_message))
                    
                    # Send push notification
                    if fcm_token:
                        send_push_notification(
                            fcm_token,
                            "Order Status Update",
                            notification_message
                        )
        
        flash(f"Order status updated to {new_status}.", "success")
    
    return redirect(url_for('order_details', order_id=order_id))

@app.route('/cancel_order/<int:order_id>', methods=['POST'])
def cancel_order(order_id):
    if 'username' not in session:
        return redirect(url_for('login'))

    with get_db_connection() as conn:
        cur = conn.cursor()
        
        # Get current user ID
        cur.execute("SELECT id FROM users WHERE username = %s", (session['username'],))
        user = cur.fetchone()
        if not user:
            flash("User not found.", "error")
            return redirect(url_for('my_orders'))
        
        user_id = user[0]
        
        # Check if user owns this order
        cur.execute("SELECT owner_id FROM orders WHERE id = %s", (order_id,))
        order_owner = cur.fetchone()
        if not order_owner or order_owner[0] != user_id:
            flash("You can only cancel your own orders.", "error")
            return redirect(url_for('my_orders'))
        
        # Update order message to include cancellation
        cur.execute("""
            UPDATE orders 
            SET message = message || '\n\nOrder Cancelled by customer on ' || NOW()
            WHERE id = %s
        """, (order_id,))
        
        # Notify all accepted providers about cancellation
        cur.execute("""
            SELECT oa.provider_id, u.username, u.fcm_token
            FROM order_acceptance oa
            JOIN users u ON u.id = oa.provider_id
            WHERE oa.order_id = %s AND oa.accepted = TRUE
        """, (order_id,))
        
        accepted_providers = cur.fetchall()
        providers_notified = 0
        
        for provider_id, provider_username, fcm_token in accepted_providers:
            # Send notification to provider
            cur.execute("""
                INSERT INTO notifications (to_user_id, from_user_id, order_id, message, created_at, is_read)
                VALUES (%s, %s, %s, %s, NOW(), FALSE)
            """, (provider_id, user_id, order_id, f"Order #{order_id} has been cancelled by the customer."))
            
            # Send push notification if token exists
            if fcm_token:
                send_push_notification(
                    fcm_token,
                    "Order Cancelled",
                    f"Order #{order_id} has been cancelled by the customer."
                )
            
            providers_notified += 1
        
        conn.commit()
        
        if providers_notified > 0:
            flash(f"Order cancelled successfully. {providers_notified} provider(s) have been notified.", "success")
        else:
            flash("Order cancelled successfully.", "success")
    
    return redirect(url_for('my_orders'))


@app.route('/reject_provider/<int:order_id>', methods=['POST'])
def reject_provider(order_id):
    if 'username' not in session:
        return redirect('/login')
    
    rejected_provider_id = request.form.get('rejected_provider_id')
    if not rejected_provider_id:
        flash("No provider selected for rejection", "error")
        return redirect(url_for('notifications'))
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    # Get order owner
    cur.execute("SELECT owner_id FROM orders WHERE id = %s", (order_id,))
    order_result = cur.fetchone()
    if not order_result:
        flash("Order not found", "error")
        return redirect(url_for('notifications'))
    
    owner_id = order_result[0]
    
    # Check if current user is the order owner
    cur.execute("SELECT id FROM users WHERE username = %s", (session['username'],))
    current_user_id = cur.fetchone()[0]
    
    if owner_id != current_user_id:
        flash("You don't have permission to reject providers for this order", "error")
        return redirect(url_for('notifications'))
    
    # Update order_acceptance to mark as rejected
    cur.execute("""
        UPDATE order_acceptance 
        SET accepted = FALSE 
        WHERE order_id = %s AND provider_id = %s
    """, (order_id, rejected_provider_id))
    
    # Notify rejected provider
    cur.execute("""
        INSERT INTO notifications (to_user_id, from_user_id, order_id, message, created_at, is_read)
        VALUES (%s, %s, %s, %s, NOW(), FALSE)
    """, (rejected_provider_id, current_user_id, order_id, f"You have been rejected by owner for Order #{order_id}."))
    
    # Send push notification
    cur.execute("SELECT fcm_token FROM users WHERE id = %s", (rejected_provider_id,))
    token_result = cur.fetchone()
    if token_result and token_result[0]:
        send_push_notification(
            token_result[0],
            "Order Update",
            f"Sorry, you were not selected for Order #{order_id}."
        )
    
    conn.commit()
    cur.close()
    conn.close()
    
    flash("Provider rejected successfully", "success")
    return redirect(url_for('notifications'))

@app.route('/mark_all_read')
def mark_all_read():
    if 'username' not in session:
        return redirect('/login')
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    # Get current user ID
    cur.execute("SELECT id FROM users WHERE username = %s", (session['username'],))
    user_id = cur.fetchone()[0]
    
    # Mark all notifications as read
    cur.execute("""
        UPDATE notifications 
        SET is_read = TRUE 
        WHERE to_user_id = %s
    """, (user_id,))
    
    conn.commit()
    cur.close()
    conn.close()
    
    flash("All notifications marked as read", "success")
    return redirect(url_for('notifications'))

# ---------- WALLET & SUBSCRIPTIONS ----------
@app.route('/wallet')
@login_required
def wallet():
    """Display wallet and subscription plans"""
    if 'username' not in session:
        return redirect(url_for('login'))
    
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        # Get current user info
        cur.execute("SELECT business_type, account_type FROM users WHERE username = %s", (session['username'],))
        user = cur.fetchone()
        
        if not user or user['account_type'] != 'business':
            flash("Wallet feature is only available for helpers.", "error")
            return redirect(url_for('home'))
        
        # Get subscription plan for this category
        cur.execute("SELECT * FROM subscription_plans WHERE category = %s", (user['business_type'],))
        plan = cur.fetchone()
        
        # Get all active/expired subscriptions for this helper
        cur.execute("""
            SELECT * FROM subscriptions 
            WHERE helper_username = %s 
            ORDER BY created_at DESC
        """, (session['username'],))
        history = cur.fetchall()
        
        # Auto-update expired subscriptions
        cur.execute("""
            UPDATE subscriptions 
            SET status = 'expired' 
            WHERE helper_username = %s 
            AND end_date < CURRENT_DATE 
            AND status = 'active'
        """, (session['username'],))
        conn.commit()
        
        # Prepare plan data with status
        plans = []
        if plan:
            # Check if user has active subscription
            cur.execute("SELECT CURRENT_DATE")
            current_date = cur.fetchone()['current_date']
            
            active_sub = None
            for sub in history:
                if sub['status'] == 'active' and sub['end_date'] >= current_date:
                    if active_sub is None or sub['end_date'] > active_sub['end_date']:
                        active_sub = sub
            
            plan_dict = dict(plan)
            plan_dict['is_active'] = False
            plan_dict['is_expired'] = False
            
            if active_sub:
                plan_dict['is_active'] = True
                plan_dict['end_date'] = active_sub['end_date']
            elif history:
                plan_dict['is_expired'] = True
            
            # Add icon based on category
            category_icons = {
                'Cleaning': '🧹',
                'Plumbing': '🔧',
                'Electrician': '⚡',
                'Vehicle': '🚗',
                'Painting': '🎨',
                'Carpentry': '🪚'
            }
            plan_dict['icon'] = category_icons.get(user['business_type'], '💼')
            
            plans = [plan_dict]
        
        # Check if subscription is expired and show message
        subscription_message = None
        if history:
            latest = history[0]
            if latest['status'] == 'expired':
                subscription_message = "Your subscription has expired. Please re-subscribe to receive new orders."
        
        # Get unpaid fines for this helper
        cur.execute("""
            SELECT SUM(fine_amount) as total_fines, COUNT(*) as fine_count
            FROM helper_fines
            WHERE helper_username = %s AND status = 'unpaid'
        """, (session['username'],))
        fines_info = cur.fetchone()
        total_fines = fines_info['total_fines'] or 0
        fine_count = fines_info['fine_count'] or 0
        
        # Get individual fines for display
        cur.execute("""
            SELECT * FROM helper_fines
            WHERE helper_username = %s AND status = 'unpaid'
            ORDER BY created_at DESC
        """, (session['username'],))
        unpaid_fines = cur.fetchall()
        
        return render_template('subscription.html', 
                             plans=plans, 
                             history=history, 
                             subscription_message=subscription_message,
                             total_fines=total_fines,
                             fine_count=fine_count,
                             unpaid_fines=unpaid_fines)

@app.route('/subscribe/<category>', methods=['POST'])
@login_required
def subscribe(category):
    """Handle subscription payment"""
    if 'username' not in session:
        return redirect(url_for('login'))
    
    with get_db_connection() as conn:
        cur = conn.cursor()
        
        # Verify user is a helper
        cur.execute("SELECT account_type FROM users WHERE username = %s", (session['username'],))
        user = cur.fetchone()
        
        if not user or user[0] != 'business':
            flash("Only helpers can subscribe.", "error")
            return redirect(url_for('wallet'))
        
        # Get subscription plan
        cur.execute("SELECT * FROM subscription_plans WHERE category = %s", (category,))
        plan = cur.fetchone()
        
        if not plan:
            flash("Subscription plan not found for this category.", "error")
            return redirect(url_for('wallet'))
        
        # Check if already has active subscription
        cur.execute("""
            SELECT * FROM subscriptions 
            WHERE helper_username = %s 
            AND category = %s 
            AND status = 'active' 
            AND end_date >= CURRENT_DATE
        """, (session['username'], category))
        existing = cur.fetchone()
        
        if existing:
            flash("You already have an active subscription for this category.", "info")
            return redirect(url_for('wallet'))
        
        # Get unpaid fines for this helper
        cur.execute("""
            SELECT SUM(fine_amount) as total_fines
            FROM helper_fines
            WHERE helper_username = %s AND status = 'unpaid'
        """, (session['username'],))
        fines_info = cur.fetchone()
        total_fines = fines_info['total_fines'] or 0
        
        # Calculate total due (subscription + fines)
        total_due = plan[2] + total_fines  # plan[2] is amount
        
        # Create subscription (7 days from now)
        from datetime import datetime, timedelta
        start_date = datetime.now().date()
        end_date = start_date + timedelta(days=7)
        
        # Mark fines as paid when subscription is created
        if total_fines > 0:
            cur.execute("""
                UPDATE helper_fines
                SET status = 'paid', paid_at = NOW()
                WHERE helper_username = %s AND status = 'unpaid'
            """, (session['username'],))
        
        cur.execute("""
            INSERT INTO subscriptions (helper_username, category, start_date, end_date, status, total_due)
            VALUES (%s, %s, %s, %s, 'active', %s)
        """, (session['username'], category, start_date, end_date, total_due))
        
        conn.commit()
        
        if total_fines > 0:
            flash(f"Successfully subscribed to {category} plan for 1 week! Total paid: ₹{total_due} (₹{plan[2]} subscription + ₹{total_fines} fines)", "success")
        else:
            flash(f"Successfully subscribed to {category} plan for 1 week!", "success")
        return redirect(url_for('wallet'))

# ---------- ORDER OFFERS MANAGEMENT ----------
@app.route('/view_offers/<int:order_id>')
@login_required
def view_offers(order_id):
    """Display all offers for a user's order"""
    if 'username' not in session:
        return redirect(url_for('login'))
    
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        # Verify user owns this order
        cur.execute("SELECT owner_id FROM orders WHERE id = %s", (order_id,))
        order_result = cur.fetchone()
        
        if not order_result:
            flash("Order not found.", "error")
            return redirect(url_for('home'))
        
        # Check if current user is the owner
        cur.execute("SELECT id FROM users WHERE username = %s", (session['username'],))
        current_user = cur.fetchone()
        
        if order_result['owner_id'] != current_user['id']:
            flash("You don't have permission to view this order.", "error")
            return redirect(url_for('home'))
        
        # Get order details
        cur.execute("""
            SELECT o.*, s.service_name, l.location_name 
            FROM orders o
            JOIN services s ON s.id = o.service_id
            JOIN locations l ON l.id = o.location_id
            WHERE o.id = %s
        """, (order_id,))
        order = cur.fetchone()
        
        # Get all offers for this order with helper info
        cur.execute("""
            SELECT 
                or_req.*,
                u.username,
                u.business_type,
                u.location,
                u.profile_pic,
                u.phone,
                COALESCE(AVG(f.rating), 0) as avg_rating,
                COUNT(f.id) as review_count
            FROM order_requests or_req
            JOIN users u ON u.username = or_req.helper_username
            LEFT JOIN feedback f ON f.to_user_id = u.id
            WHERE or_req.order_id = %s
            GROUP BY or_req.id, u.id
            ORDER BY or_req.timestamp DESC
        """, (order_id,))
        offers = cur.fetchall()
        
        # Auto-expire old requests (older than 24 hours)
        cur.execute("""
            UPDATE order_requests 
            SET status = 'expired' 
            WHERE order_id = %s 
                AND status = 'pending' 
                AND timestamp < NOW() - INTERVAL '24 hours'
        """, (order_id,))
        conn.commit()
    
    return render_template('view_offers.html', order=order, offers=offers)

@app.route('/accept_offer/<int:request_id>', methods=['POST'])
@login_required
def accept_offer(request_id):
    """Accept a helper's offer"""
    if 'username' not in session:
        return redirect(url_for('login'))
    
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        # Get request details
        cur.execute("SELECT * FROM order_requests WHERE id = %s", (request_id,))
        req = cur.fetchone()
        
        if not req:
            flash("Offer not found.", "error")
            return redirect(url_for('home'))
        
        # Verify user owns this order
        cur.execute("SELECT owner_id FROM orders WHERE id = %s", (req['order_id'],))
        order_owner_id = cur.fetchone()['owner_id']
        
        cur.execute("SELECT id FROM users WHERE username = %s", (session['username'],))
        current_user_id = cur.fetchone()['id']
        
        if order_owner_id != current_user_id:
            flash("You don't have permission to accept this offer.", "error")
            return redirect(url_for('home'))
        
        # Update accepted offer in order_requests
        cur.execute("""
            UPDATE order_requests 
            SET status = 'accepted' 
            WHERE id = %s
        """, (request_id,))
        
        # Reject all other pending offers for this order
        cur.execute("""
            UPDATE order_requests 
            SET status = 'rejected' 
            WHERE order_id = %s 
                AND id != %s 
                AND status = 'pending'
        """, (req['order_id'], request_id))

        # Reflect selection in order_acceptance table as the canonical approval source
        # Get helper's user id
        cur.execute("SELECT id FROM users WHERE username = %s", (req['helper_username'],))
        ah_row = cur.fetchone()
        accepted_helper_id = ah_row['id'] if ah_row and 'id' in ah_row else None

        # Mark final selected helper
        if accepted_helper_id:
            cur.execute("""
                UPDATE order_acceptance SET final_selected = TRUE, accepted = TRUE
                WHERE order_id = %s AND provider_id = %s
            """, (req['order_id'], accepted_helper_id))

        # Mark all others as not accepted
        cur.execute("""
            UPDATE order_acceptance SET accepted = FALSE, final_selected = FALSE
            WHERE order_id = %s AND provider_id != %s
        """, (req['order_id'], accepted_helper_id if accepted_helper_id else -1))

        # Update orders table with status and accepted helper if columns exist (prevent exceptions)
        cur.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'orders' AND column_name IN ('status','accepted_helper')
        """)
        cols = {row['column_name'] for row in cur.fetchall()} if cur.description else set()
        set_clauses = []
        params = []
        if 'status' in cols:
            set_clauses.append("status = 'accepted'")
        if 'accepted_helper' in cols:
            set_clauses.append("accepted_helper = %s")
            params.append(req['helper_username'])
        if set_clauses:
            sql = f"UPDATE orders SET {', '.join(set_clauses)} WHERE id = %s"
            params.append(req['order_id'])
            cur.execute(sql, tuple(params))

        # Fetch contextual info for notifications
        cur.execute("""
            SELECT s.service_name, u_owner.username AS owner_username
            FROM orders o
            JOIN services s ON s.id = o.service_id
            JOIN users u_owner ON u_owner.id = o.owner_id
            WHERE o.id = %s
        """, (req['order_id'],))
        ctx = cur.fetchone() or {}
        
        # Notify the accepted helper
        cur.execute("SELECT id, phone FROM users WHERE username = %s", (req['helper_username'],))
        helper_row = cur.fetchone() or {}
        helper_id = helper_row.get('id')

        service_name = ctx.get('service_name', 'this service')
        approved_msg = f"🎉 Your request for {service_name} has been approved!"
        if helper_id:
            cur.execute("""
                INSERT INTO notifications (to_user_id, from_user_id, order_id, message, created_at, is_read)
                VALUES (%s, %s, %s, %s, NOW(), FALSE)
            """, (helper_id, current_user_id, req['order_id'], approved_msg))

        # Push notification to accepted helper
        if helper_id:
            cur.execute("SELECT fcm_token FROM users WHERE id = %s", (helper_id,))
            token_result = cur.fetchone()
            if token_result and token_result.get('fcm_token'):
                send_push_notification(
                    token_result['fcm_token'],
                    "Offer Approved",
                    approved_msg
                )

        # Notify rejected helpers (those who requested this order but weren't selected)
        cur.execute("""
            SELECT DISTINCT u.id, u.username, u.fcm_token
            FROM order_requests r
            JOIN users u ON u.username = r.helper_username
            WHERE r.order_id = %s AND r.id != %s AND r.status != 'accepted'
        """, (req['order_id'], request_id))
        rejected_rows = cur.fetchall()
        rejection_msg = f"❌ Your request for {service_name} was not approved."
        for rhelper in rejected_rows:
            cur.execute("""
                INSERT INTO notifications (to_user_id, from_user_id, order_id, message, created_at, is_read)
                VALUES (%s, %s, %s, %s, NOW(), FALSE)
            """, (rhelper['id'], current_user_id, req['order_id'], rejection_msg))
            if rhelper and ('fcm_token' in rhelper) and rhelper['fcm_token']:
                send_push_notification(rhelper['fcm_token'], "Request Not Approved", rejection_msg)
        
        conn.commit()
    
    flash(f"You accepted the offer of ₹{req['amount']} from {req['helper_username']}", "success")
    return redirect(url_for('view_offers', order_id=req['order_id']))

@app.route('/my_requests')
@login_required
def my_requests():
    """Display helper's order requests"""
    if 'username' not in session:
        return redirect(url_for('login'))
    
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        # Verify user is a helper
        cur.execute("SELECT account_type FROM users WHERE username = %s", (session['username'],))
        user = cur.fetchone()
        
        if not user or user['account_type'] != 'business':
            flash("This feature is only available for helpers.", "error")
            return redirect(url_for('home'))
        
        # Get all requests by this helper with order details
        cur.execute("""
            SELECT 
                or_req.*,
                o.message as order_message,
                o.created_at as order_created_at,
                o.image_path,
                s.service_name,
                l.location_name,
                (SELECT username FROM users WHERE id = o.owner_id) as customer_username
            FROM order_requests or_req
            JOIN orders o ON o.id = or_req.order_id
            JOIN services s ON s.id = o.service_id
            JOIN locations l ON l.id = o.location_id
            WHERE or_req.helper_username = %s
            ORDER BY or_req.timestamp DESC
        """, (session['username'],))
        requests = cur.fetchall()
        
        # Auto-expire old requests
        cur.execute("""
            UPDATE order_requests 
            SET status = 'expired' 
            WHERE helper_username = %s 
                AND status = 'pending' 
                AND timestamp < NOW() - INTERVAL '24 hours'
        """, (session['username'],))
        conn.commit()
    
    return render_template('my_requests.html', requests=requests)


# ---------- OTP VERIFICATION SYSTEM ----------
@app.route('/generate_otp/<int:order_id>', methods=['POST'])
@login_required
def generate_otp(order_id):
    """Generate OTP for order verification (Helper side) - Works for both direct bookings and legacy orders"""
    if 'username' not in session:
        return jsonify({'success': False, 'message': 'Not authenticated'}), 401
    
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        # Get current user ID
        cursor.execute("SELECT id FROM users WHERE username = %s", (session['username'],))
        current_user = cursor.fetchone()
        if not current_user:
            return jsonify({'success': False, 'message': 'User not found'}), 404
        current_user_id = current_user['id']
        
        # Get order details - check both direct bookings and legacy orders
        cursor.execute("""
            SELECT o.id, o.owner_id, o.user_id, o.helper_id, o.is_direct_booking, 
                   o.status, o.message as order_message, o.about,
                   (SELECT username FROM users WHERE id = o.owner_id) as owner_username,
                   (SELECT username FROM users WHERE id = o.user_id) as user_username,
                   (SELECT service_name FROM services WHERE id = o.service_id) as service_name,
                   (SELECT location_name FROM locations WHERE id = o.location_id) as location_name
            FROM orders o
            WHERE o.id = %s
        """, (order_id,))
        
        order_info = cursor.fetchone()
        
        if not order_info:
            return jsonify({'success': False, 'message': 'Order not found'}), 404
        
        # Check if order is accepted
        if order_info.get('status') != 'accepted':
            return jsonify({'success': False, 'message': 'Order must be accepted before generating OTP'}), 400
        
        # Verify helper is authorized (for direct bookings, check helper_id; for legacy, check order_requests/order_acceptance)
        is_direct = order_info.get('is_direct_booking', False)
        is_authorized = False
        owner_id = None
        
        if is_direct:
            # Direct booking: check if current user is the helper
            if order_info.get('helper_id') == current_user_id:
                is_authorized = True
                owner_id = order_info.get('user_id')  # For direct bookings, user_id is the customer
        else:
            # Legacy order: check order_requests or order_acceptance
            owner_id = order_info.get('owner_id')
            cursor.execute("""
                SELECT 1 FROM order_requests 
                WHERE order_id = %s AND helper_username = %s AND status = 'accepted'
            """, (order_id, session['username']))
            if cursor.fetchone():
                is_authorized = True
            else:
                cursor.execute("""
                    SELECT 1 FROM order_acceptance 
                    WHERE order_id = %s AND provider_id = %s 
                    AND (final_selected = TRUE OR accepted = TRUE)
                """, (order_id, current_user_id))
                if cursor.fetchone():
                    is_authorized = True
        
        if not is_authorized or not owner_id:
            return jsonify({'success': False, 'message': 'Order not found or you are not the approved helper'}), 404
        
        # Check if already verified
        cursor.execute("SELECT is_verified, status FROM orders WHERE id = %s", (order_id,))
        order_check = cursor.fetchone()
        if order_check and order_check.get('is_verified'):
            return jsonify({'success': False, 'message': 'Order already verified'}), 400
        
        # Generate 4-digit OTP
        otp = str(random.randint(1000, 9999))
        
        # Set expiration (10 minutes)
        expires_at = datetime.now() + timedelta(minutes=10)
        
        # Reset OTP attempts and delete any existing OTPs for this order
        cursor.execute("DELETE FROM order_otps WHERE order_id = %s", (order_id,))
        cursor.execute("UPDATE orders SET otp_attempts = 0 WHERE id = %s", (order_id,))
        
        # Store OTP in orders table (for direct bookings) and order_otps table (for compatibility)
        cursor.execute("""
            UPDATE orders 
            SET otp = %s, otp_expires_at = %s
            WHERE id = %s
        """, (otp, expires_at, order_id))
        
        cursor.execute("""
            INSERT INTO order_otps (order_id, otp, expires_at)
            VALUES (%s, %s, %s)
        """, (order_id, otp, expires_at))
        
        # Get customer details
        cursor.execute("SELECT username FROM users WHERE id = %s", (owner_id,))
        customer = cursor.fetchone()
        customer_username = customer['username'] if customer else 'Customer'
        helper_username = session['username']
        
        # Get order details text
        order_details = order_info.get('about') or order_info.get('order_message') or 'No details provided'
        service_name = order_info.get('service_name') or 'Service'
        location_name = order_info.get('location_name') or 'Location'
        expires_time = expires_at.strftime("%I:%M %p on %B %d, %Y")
        
        # Create detailed OTP notification message
        otp_message = f"🔐 OTP for Order Verification\n\nOrder #: {order_id}\nOTP: {otp}\nValid Until: {expires_time}\n\nHelper: {helper_username}\nService: {service_name}\nLocation: {location_name}\n\nDetails: {order_details[:100]}{'...' if len(order_details) > 100 else ''}"
        
        # Ensure schema and notify the customer about OTP
        ensure_notifications_schema()
        cursor.execute("""
            INSERT INTO notifications (to_user_id, from_user_id, order_id, message, type, created_at, is_read)
            VALUES (%s, %s, %s, %s, 'otp_notification', NOW(), FALSE)
        """, (owner_id, current_user_id, order_id, otp_message))
        
        # Send push notification
        cursor.execute("SELECT fcm_token FROM users WHERE id = %s", (owner_id,))
        owner_token = cursor.fetchone()
        if owner_token and owner_token.get('fcm_token'):
            send_push_notification(
                owner_token['fcm_token'],
                f"🔐 OTP for Order #{order_id}",
                f"OTP: {otp} | Valid until {expires_time} | Helper: {helper_username}"
            )
        
        conn.commit()
        
        return jsonify({'success': True, 'message': 'OTP generated and sent to the customer', 'expires_at': expires_at.isoformat()})

@app.route('/verify_otp/<int:order_id>', methods=['POST'])
@login_required
def verify_otp(order_id):
    """Verify OTP entered by helper"""
    if 'username' not in session:
        return jsonify({'success': False, 'message': 'Not authenticated'}), 401
    
    data = request.get_json()
    entered_otp = data.get('otp', '').strip()
    
    if not entered_otp or len(entered_otp) != 4:
        return jsonify({'success': False, 'message': 'Invalid OTP format'}), 400
    
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        # Get current user ID
        cursor.execute("SELECT id FROM users WHERE username = %s", (session['username'],))
        current_user = cursor.fetchone()
        if not current_user:
            return jsonify({'success': False, 'message': 'User not found'}), 404
        current_user_id = current_user['id']
        
        # Verify helper is the approved provider (handles both direct bookings and legacy orders)
        cursor.execute("""
            SELECT o.id, o.owner_id, o.user_id, o.helper_id, o.is_direct_booking,
                   (SELECT username FROM users WHERE id = COALESCE(o.owner_id, o.user_id)) as owner_username,
                   (SELECT username FROM users WHERE id = o.helper_id) as helper_username
            FROM orders o
            WHERE o.id = %s
            LIMIT 1
        """, (order_id,))
        
        order_info = cursor.fetchone()
        
        if not order_info:
            return jsonify({'success': False, 'message': 'Order not found'}), 404
        
        # Check if order is accepted
        cursor.execute("SELECT status FROM orders WHERE id = %s", (order_id,))
        order_status = cursor.fetchone()
        if not order_status or order_status['status'] != 'accepted':
            return jsonify({'success': False, 'message': 'Order must be accepted before verification'}), 400
        
        # Verify authorization: for direct bookings, check helper_id; for legacy, check order_requests/order_acceptance
        is_direct = order_info.get('is_direct_booking', False)
        is_authorized = False
        
        if is_direct:
            # Direct booking: check if current user is the helper
            if order_info.get('helper_id') == current_user_id:
                is_authorized = True
        else:
            # Legacy order: check order_requests or order_acceptance
            cursor.execute("""
                SELECT 1 FROM order_requests 
                WHERE order_id = %s AND helper_username = %s AND status = 'accepted'
            """, (order_id, session['username']))
            if cursor.fetchone():
                is_authorized = True
            else:
                cursor.execute("""
                    SELECT 1 FROM order_acceptance 
                    WHERE order_id = %s AND provider_id = %s 
                    AND (final_selected = TRUE OR accepted = TRUE)
                """, (order_id, current_user_id))
                if cursor.fetchone():
                    is_authorized = True
        
        if not is_authorized:
            return jsonify({'success': False, 'message': 'You are not authorized to verify this order'}), 403
        
        owner_id = order_info.get('owner_id') or order_info.get('user_id')
        
        # First, delete all expired OTPs (security: auto-cleanup expired OTPs)
        cursor.execute("DELETE FROM order_otps WHERE expires_at < NOW()")
        
        # Get current OTP for this order (check both order_otps table and orders table for direct bookings)
        cursor.execute("""
            SELECT otp, expires_at, is_verified, created_at
            FROM order_otps
            WHERE order_id = %s
            ORDER BY created_at DESC
            LIMIT 1
        """, (order_id,))
        
        otp_record = cursor.fetchone()
        
        # If not found in order_otps, check orders table (for direct bookings)
        if not otp_record:
            cursor.execute("""
                SELECT otp, otp_expires_at as expires_at, FALSE as is_verified, created_at
                FROM orders
                WHERE id = %s AND otp IS NOT NULL
            """, (order_id,))
        otp_record = cursor.fetchone()
        
        if not otp_record:
            return jsonify({'success': False, 'message': 'No OTP found for this order. Please generate one first.'}), 404
        
        # Check if already verified
        if otp_record['is_verified']:
            return jsonify({'success': False, 'message': 'OTP already verified'}), 400
        
        # Check if expired (double check after cleanup)
        if datetime.now() > otp_record['expires_at']:
            # Delete this expired OTP
            cursor.execute("DELETE FROM order_otps WHERE order_id = %s", (order_id,))
            conn.commit()
            return jsonify({'success': False, 'message': 'OTP has expired. Please generate a new one.'}), 400
        
        # Check OTP attempts (limit to 3)
        cursor.execute("SELECT otp_attempts FROM orders WHERE id = %s", (order_id,))
        attempts_result = cursor.fetchone()
        current_attempts = attempts_result['otp_attempts'] if attempts_result else 0
        
        if current_attempts >= 3:
            return jsonify({'success': False, 'message': 'Maximum OTP attempts (3) exceeded. Please generate a new OTP.'}), 400
        
        # Verify OTP
        if entered_otp != otp_record['otp']:
            # Increment attempt counter
            cursor.execute("""
                UPDATE orders 
                SET otp_attempts = COALESCE(otp_attempts, 0) + 1
                WHERE id = %s
            """, (order_id,))
            conn.commit()
            remaining = 3 - (current_attempts + 1)
            return jsonify({'success': False, 'message': f'Invalid OTP. {remaining} attempt(s) remaining.'}), 400
        
        # OTP is correct - mark as verified and delete the OTP (security: one-time use)
        cursor.execute("""
            UPDATE order_otps 
            SET is_verified = TRUE, verified_at = NOW()
            WHERE order_id = %s
        """, (order_id,))
        
        # Delete the OTP after successful verification for security
        cursor.execute("DELETE FROM order_otps WHERE order_id = %s", (order_id,))
        
        # Mark order as verified and set status to 'in_progress', set verification deadline (24 hours)
        verification_deadline = datetime.now() + timedelta(hours=24)
        helper_id = order_info.get('helper_id') or current_user_id
        
        cursor.execute("""
            UPDATE orders 
            SET is_verified = TRUE, 
                verified_at = NOW(),
                verification_deadline = %s,
                verification_helper_id = %s,
                status = 'in_progress',
                otp = NULL,
                otp_expires_at = NULL
            WHERE id = %s
        """, (verification_deadline, helper_id, order_id))
        
        # Notify both user and helper
        owner_id = order_info.get('owner_id') or order_info.get('user_id')
        verification_msg_user = f"✅ Order #{order_id} has been verified by helper. You have 24 hours to mark it as Completed, Processing, or Cancel."
        verification_msg_helper = f"✅ Order #{order_id} verification successful! Order status changed to 'In Progress'."
        
        # Notify owner
        cursor.execute("""
            INSERT INTO notifications (to_user_id, from_user_id, order_id, message, created_at, is_read)
            VALUES (%s, %s, %s, %s, NOW(), FALSE)
        """, (owner_id, helper_id, order_id, verification_msg_user))
        
        # Notify helper
        cursor.execute("""
            INSERT INTO notifications (to_user_id, from_user_id, order_id, message, created_at, is_read)
            VALUES (%s, %s, %s, %s, NOW(), FALSE)
        """, (helper_id, owner_id, order_id, verification_msg_helper))
        
        # Send push notifications
        cursor.execute("SELECT id, fcm_token FROM users WHERE id IN (%s, %s)", (owner_id, helper_id))
        tokens = cursor.fetchall()
        for token_row in tokens:
            if token_row and token_row.get('fcm_token'):
                if token_row['id'] == owner_id:
                    send_push_notification(token_row['fcm_token'], "Order Verified", verification_msg_user)
                elif token_row['id'] == helper_id:
                    send_push_notification(token_row['fcm_token'], "Verification Successful", verification_msg_helper)
        
        conn.commit()
        
        return jsonify({'success': True, 'message': 'OTP verified successfully! Order verification completed.'})

@app.route('/user_action/<int:order_id>', methods=['POST'])
@login_required
def user_action(order_id):
    """Handle user action (Completed, Processing, Cancel)"""
    if 'username' not in session:
        return jsonify({'success': False, 'message': 'Not authenticated'}), 401
    
    data = request.get_json()
    action = data.get('action', '').strip().lower()
    
    valid_actions = ['completed', 'processing', 'cancel']
    if action not in valid_actions:
        return jsonify({'success': False, 'message': 'Invalid action. Use: completed, processing, or cancel'}), 400
    
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        # Get current user ID
        cursor.execute("SELECT id FROM users WHERE username = %s", (session['username'],))
        current_user = cursor.fetchone()
        if not current_user:
            return jsonify({'success': False, 'message': 'User not found'}), 404
        current_user_id = current_user['id']
        
        # Verify user owns this order (handles both direct bookings and legacy orders)
        cursor.execute("""
            SELECT o.id, o.owner_id, o.user_id, o.helper_id, o.is_direct_booking, o.is_verified, o.verification_helper_id,
                   (SELECT username FROM users WHERE id = COALESCE(o.verification_helper_id, o.helper_id)) as helper_username
            FROM orders o
            WHERE o.id = %s
        """, (order_id,))
        
        order_info = cursor.fetchone()
        
        if not order_info:
            return jsonify({'success': False, 'message': 'Order not found'}), 404
        
        # Check if user is authorized (for direct bookings: user_id; for legacy: owner_id)
        is_direct = order_info.get('is_direct_booking', False)
        is_authorized = False
        
        if is_direct:
            # Direct booking: check if current user is the customer (user_id)
            if order_info.get('user_id') == current_user_id:
                is_authorized = True
        else:
            # Legacy order: check if current user is the owner (owner_id)
            if order_info.get('owner_id') == current_user_id:
                is_authorized = True
        
        if not is_authorized:
            return jsonify({'success': False, 'message': 'Order not found or you do not have permission'}), 403
        
        if not order_info.get('is_verified'):
            return jsonify({'success': False, 'message': 'Order must be verified first before taking action'}), 400
        
        # Update order with user action
        if action == 'processing':
            # Extend deadline by 24 hours
            new_deadline = datetime.now() + timedelta(hours=24)
            cursor.execute("""
                UPDATE orders 
                SET user_action = %s, 
                    user_action_at = NOW(),
                    verification_deadline = %s
                WHERE id = %s
            """, (action, new_deadline, order_id))
        else:
            # Completed or Cancel - clear deadline
            cursor.execute("""
                UPDATE orders 
                SET user_action = %s, 
                    user_action_at = NOW(),
                    verification_deadline = NULL
                WHERE id = %s
            """, (action, order_id))
        
        # Notify helper
        helper_id = order_info.get('verification_helper_id')
        helper_username = order_info.get('helper_username')
        
        # For direct bookings, get helper_id from order if verification_helper_id is not set
        if not helper_id and is_direct:
            helper_id = order_info.get('helper_id')
        
        action_messages = {
            'completed': f'✅ Order #{order_id} has been marked as Completed by the customer.',
            'processing': f'🔄 Order #{order_id} is marked as Processing. Timer extended by 24 hours.',
            'cancel': f'❌ Order #{order_id} has been cancelled by the customer.'
        }
        
        notification_msg = action_messages.get(action, f'Order #{order_id} action: {action}')
        
        if helper_id:
            ensure_notifications_schema()
            cursor.execute("""
                INSERT INTO notifications (to_user_id, from_user_id, order_id, message, created_at, is_read)
                VALUES (%s, %s, %s, %s, NOW(), FALSE)
            """, (helper_id, current_user_id, order_id, notification_msg))
            
            # Send push notification
            cursor.execute("SELECT fcm_token FROM users WHERE id = %s", (helper_id,))
            helper_token = cursor.fetchone()
            if helper_token and helper_token.get('fcm_token'):
                send_push_notification(helper_token['fcm_token'], f"Order {action.title()}", notification_msg)
        
        conn.commit()
        
        return jsonify({'success': True, 'message': f'Order marked as {action.title()} successfully'})

@app.route('/check_order_status/<int:order_id>')
@login_required
def check_order_status(order_id):
    """Check order verification status and deadline"""
    if 'username' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        cursor.execute("""
            SELECT o.id, o.is_verified, o.verification_deadline, o.user_action, o.user_action_at,
                   o.owner_id, o.verification_helper_id,
                   (SELECT username FROM users WHERE id = o.owner_id) as owner_username,
                   (SELECT id FROM users WHERE username = %s) as current_user_id
            FROM orders o
            WHERE o.id = %s
        """, (session['username'], order_id))
        
        order = cursor.fetchone()
        
        if not order:
            return jsonify({'error': 'Order not found'}), 404
        
        # Check if user has permission
        if order['owner_id'] != order['current_user_id'] and order['verification_helper_id'] != order['current_user_id']:
            # Allow if user is admin
            if session['username'] != 'adime':
                return jsonify({'error': 'Permission denied'}), 403
        
        result = {
            'is_verified': order.get('is_verified', False),
            'verification_deadline': order['verification_deadline'].isoformat() if order.get('verification_deadline') else None,
            'user_action': order.get('user_action'),
            'user_action_at': order['user_action_at'].isoformat() if order.get('user_action_at') else None,
            'is_owner': order['owner_id'] == order['current_user_id']
        }
        
        # Calculate time remaining if deadline exists
        if result['verification_deadline']:
            deadline = datetime.fromisoformat(result['verification_deadline'].replace('Z', '+00:00'))
            now = datetime.now()
            if deadline.tzinfo is None:
                deadline = deadline.replace(tzinfo=datetime.now().astimezone().tzinfo)
            remaining = deadline - now
            result['time_remaining_seconds'] = max(0, int(remaining.total_seconds()))
        else:
            result['time_remaining_seconds'] = None
        
        return jsonify(result)

# Background job to check for expired verifications and apply fines
def check_expired_verifications():
    """Background job to check for expired order verifications and apply fines"""
    while True:
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                
                # Find orders that have passed deadline and no user action taken
                cursor.execute("""
                    SELECT o.id, o.verification_helper_id, o.verification_deadline, o.user_action,
                           (SELECT username FROM users WHERE id = o.verification_helper_id) as helper_username
                    FROM orders o
                    WHERE o.is_verified = TRUE
                        AND o.verification_deadline IS NOT NULL
                        AND o.verification_deadline < NOW()
                        AND (o.user_action IS NULL OR o.user_action != 'completed')
                        AND o.user_action != 'cancel'
                """)
                
                expired_orders = cursor.fetchall()
                
                FINE_AMOUNT = 50  # ₹50 fine
                
                for order in expired_orders:
                    # Check if fine already applied
                    cursor.execute("""
                        SELECT id FROM helper_fines 
                        WHERE order_id = %s AND status = 'unpaid'
                    """, (order['id'],))
                    
                    existing_fine = cursor.fetchone()
                    
                    if not existing_fine:
                        # Apply fine
                        cursor.execute("""
                            INSERT INTO helper_fines (helper_username, order_id, fine_amount, status, fine_reason)
                            VALUES (%s, %s, %s, 'unpaid', %s)
                        """, (order['helper_username'], order['id'], FINE_AMOUNT, 
                              f'Order #{order["id"]} verification deadline expired without user action'))
                        
                        # Update subscription total_due for this helper
                        cursor.execute("""
                            UPDATE subscriptions 
                            SET total_due = COALESCE(total_due, 0) + %s
                            WHERE helper_username = %s AND status = 'active'
                        """, (FINE_AMOUNT, order['helper_username']))
                        
                        # Mark order as expired
                        cursor.execute("""
                            UPDATE orders 
                            SET user_action = 'expired',
                                verification_deadline = NULL
                            WHERE id = %s
                        """, (order['id'],))
                        
                        # Notify helper about fine
                        if order['verification_helper_id']:
                            # Get system/admin user ID for from_user_id (use owner_id or a default)
                            cursor.execute("SELECT owner_id FROM orders WHERE id = %s", (order['id'],))
                            owner_result = cursor.fetchone()
                            from_user_id = owner_result['owner_id'] if owner_result else order['verification_helper_id']
                            
                            cursor.execute("""
                                INSERT INTO notifications (to_user_id, from_user_id, order_id, message, created_at, is_read)
                                VALUES (%s, %s, %s, %s, NOW(), FALSE)
                            """, (order['verification_helper_id'], from_user_id, order['id'], 
                                  f'⚠️ ₹{FINE_AMOUNT} fine applied for Order #{order["id"]} - Deadline expired without user action'))
                            
                            # Push notification
                            cursor.execute("SELECT fcm_token FROM users WHERE id = %s", (order['verification_helper_id'],))
                            token_row = cursor.fetchone()
                            if token_row and token_row.get('fcm_token'):
                                send_push_notification(
                                    token_row['fcm_token'],
                                    "Fine Applied",
                                    f'₹{FINE_AMOUNT} fine applied for Order #{order["id"]}'
                                )
                
                conn.commit()
                
        except Exception as e:
            print(f"Error in check_expired_verifications: {e}")
            import traceback
            traceback.print_exc()
        
        # Run every 5 minutes
        time.sleep(300)

# Start background job in a separate thread
def start_background_jobs():
    """Start background jobs"""
    background_thread = threading.Thread(target=check_expired_verifications, daemon=True)
    background_thread.start()
    print("Background job started: Checking expired verifications")

if __name__ == '__main__':
    init_db()
    start_background_jobs()
    app.run(debug=True)
