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
from datetime import timedelta


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
        service_descriptions=service_descriptions
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
        cursor.execute("DELETE FROM users WHERE username=%s", (username,))
        conn.commit()
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
        is_admin=is_admin
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

            # Handle profile picture update
            profile_pic_file = request.files.get('profile_pic')
            filename = None
            if profile_pic_file and allowed_file(profile_pic_file.filename):
                filename = upload_to_cloudinary(profile_pic_file)

            # Update user details
            if filename:
                cursor.execute("""
                    UPDATE users SET bio=%s, price=%s, profile_pic=%s WHERE username=%s
                """, (bio, price, filename, username))
            else:
                cursor.execute("""
                    UPDATE users SET bio=%s, price=%s WHERE username=%s
                """, (bio, price, username))

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
        budget = request.form.get('budget', '')
        payment_preference = request.form.get('payment_preference', 'cash')
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
            
            if budget:
                enhanced_message += f"\nBudget: ₹{budget}"
            
            if payment_preference != 'cash':
                enhanced_message += f"\nPayment preference: {payment_preference.replace('_', ' ').title()}"
            
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
            cur.execute(""" 
                SELECT id, fcm_token, username
                FROM users 
                WHERE business_type = %s AND location = %s AND account_type = 'business'
            """, (service, location))

            providers_notified = 0
            for provider_id, token, provider_username in cur.fetchall():
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

@app.route('/notifications')
def notifications():
    if 'username' not in session:
        return redirect('/login')

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute("""
    SELECT 
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
        (
            SELECT u_provider.username
            FROM order_acceptance oa
            JOIN users u_provider ON u_provider.id = oa.provider_id
            WHERE oa.order_id = n.order_id 
              AND final_selected = TRUE
            LIMIT 1
        ) AS approved_provider,
        (
            SELECT username FROM users WHERE id = o.owner_id
        ) AS owner_username,
        (
            SELECT COUNT(*) FROM order_acceptance 
            WHERE order_id = n.order_id AND provider_id = u_from.id
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
    """, (session['username'],))

    notes = cur.fetchall()
    cur.close()
    conn.close()
    return render_template('notification.html', notifications=notes)

@app.route('/api/notifications')
def api_notifications():
    if 'username' not in session:
        return jsonify([])

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("""
    SELECT 
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
        (
            SELECT u_provider.username
            FROM order_acceptance oa
            JOIN users u_provider ON u_provider.id = oa.provider_id
            WHERE oa.order_id = n.order_id 
              AND final_selected = TRUE
            LIMIT 1
        ) AS approved_provider,
        (
            SELECT username FROM users WHERE id = o.owner_id
        ) AS owner_username,
        (
            SELECT COUNT(*) FROM order_acceptance 
            WHERE order_id = n.order_id AND provider_id = u_from.id
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
    """, (session['username'],))

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
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute("""
            SELECT 
                u.username,
                u.location,
                u.profile_pic,
                u.price,
                u.phone,
                COALESCE(AVG(f.rating), 0) AS avg_rating
            FROM users u
            LEFT JOIN feedback f ON u.id = f.to_user_id
            WHERE u.account_type = 'business' AND u.business_type = %s
            GROUP BY u.username, u.location, u.profile_pic, u.price, u.phone
            ORDER BY avg_rating DESC
        """, (service_name,))
        businesses = cursor.fetchall()
    return render_template('service.html', service_name=service_name, businesses=businesses)

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
        
        # Get order details with enhanced information
        cur.execute("""
            SELECT 
                o.*,
                s.service_name,
                l.location_name,
                u_owner.username as owner_username,
                u_owner.phone as owner_phone,
                u_owner.gmail as owner_email,
                u_owner.location as owner_location,
                oa.final_selected,
                u_provider.username as approved_provider
            FROM orders o
            JOIN services s ON s.id = o.service_id
            JOIN locations l ON l.id = o.location_id
            JOIN users u_owner ON u_owner.id = o.owner_id
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
        
        # User can access if they are the owner, approved provider, or admin
        if (order['owner_id'] != current_user['id'] and 
            order.get('approved_provider') != session['username'] and 
            session['username'] != 'adime'):
            flash("You don't have permission to view this order", "error")
            return redirect(url_for('notifications'))
        
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

    return render_template('order_details.html', 
                         order=order, 
                         tracking=tracking, 
                         accepted_providers=accepted_providers)

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


if __name__ == '__main__':
    init_db()
    app.run(debug=True)
