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
import uuid

# after your other imports, before using Cloudinary
cloudinary.config(
  cloud_name = "dqfombatw",
  api_key    = "731637769665287",
  api_secret = "e-d0C1VEJm5Dj-40EM0jNF5kjvk"
)


app = Flask(__name__)
app.secret_key = 'karthik57'


# Base paths
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATABASE_URL = "postgresql://postgres.beuvyrvloopqgffoscrd:karthik57@aws-0-ap-south-1.pooler.supabase.com:6543/postgres"
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def upload_to_cloudinary(file_storage):
    result = cloudinary.uploader.upload(
        file_storage,
        folder="helper/profile_pics",    # optional organization
        public_id=str(uuid.uuid4()),       # avoid name collisions
        overwrite=False,
        resource_type="image"
    )
    return result["secure_url"]

def get_db_connection():
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    return conn


# Initialize Firebase Admin SDK
cred = credentials.Certificate("firebase-service-account-key.json")
firebase_admin.initialize_app(cred)

def send_push_notification(token, title, body):
    # Send a push notification to a single device using FCM
    message = messaging.Message(
        notification=messaging.Notification(
            title=title,
            body=body
        ),
        token=token,
    )
    try:
        response = messaging.send(message)
        print('Successfully sent message:', response)
    except Exception as e:
        print(f'Error sending message: {e}')

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
@app.route('/', methods=['GET', 'POST'])
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
                return "Invalid username or password"

    # Not logged in and not posting — show login page
    return render_template('login.html')

@app.route('/home')
def home():
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute("SELECT DISTINCT business_type FROM users WHERE account_type='business'")
        services_from_db = [row['business_type'] for row in cursor.fetchall()]        
        cursor.execute("SELECT username FROM users WHERE account_type='business'")
        business_usernames = [row['username'] for row in cursor.fetchall()]

    predefined_services = [
        'House Cleaning', 'Kitchen Cleaning', 'Bathroom Cleaning', 'Room Cleaning', 
        'Plumbing', 'Motor Repair', 'Electrician', 'Two wheeler', 'Three wheeler', 
        'Four wheeler', 'Heavy Vehicle'
    ]    
    all_services = list(set(services_from_db + predefined_services))    
    random.shuffle(all_services)    
    random_services = all_services[:6]    
    service_images = {
        'House Cleaning': 'house_cleaning.jpg',
        'Kitchen Cleaning': 'kitchen_cleaning.jpg',
        'Bathroom Cleaning': 'bathroom_cleaning.jpg',
        'Room Cleaning': 'house_cleaning.jpg',
        'Plumbing': 'plumbing.jpg',
        'Motor Repair': 'Moter_Repair.jpg',
        'Electrician': 'electrician.jpg',
        'Two wheeler': 'two_wheeler.jpg',
        'Three wheeler': 'three_wheeler.jpg',
        'Four wheeler': 'four_wheeler.jpg',
        'Heavy Vehicle': 'heavy_vechile.jpg'
    }   
    random_service_images = {service: service_images.get(service, '') for service in random_services}

    return render_template('home.html', services=random_services, service_images=random_service_images, business_usernames=business_usernames)

@app.route('/search', methods=['GET', 'POST'])
def search():
    query = request.args.get('q', '')  # Get the search query from the URL parameters
    services = []
    business_users = []

    if query:
        with get_db_connection() as conn:
            cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

            # Search for services
            cursor.execute("""
                SELECT * FROM services
                WHERE service_name ILIKE %s
            """, (f'%{query}%',))
            services = cursor.fetchall()

            # Search for businesses based on location and business type
            cursor.execute("""
                SELECT username, business_type, location, price FROM users
                WHERE (username ILIKE %s OR location ILIKE %s) AND account_type = 'business'
            """, (f'%{query}%', f'%{query}%'))
            business_users = cursor.fetchall()

    return render_template('search.html', 
                       query=query, 
                       service_results=services, 
                       business_results=business_users)

@app.route('/admin')
def admin_dashboard():
    if 'username' not in session or session['username'] != 'adime':
        return redirect(url_for('login'))

    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute("SELECT * FROM users WHERE username != 'adime'")
        users = cursor.fetchall()

        cursor.execute("SELECT reported_user, COUNT(*) as report_count FROM reports GROUP BY reported_user")
        reported_users = cursor.fetchall()

    return render_template('adime.html', users=users, reported_users=reported_users)

@app.route('/delete_user/<username>', methods=['POST'])
def delete_user(username):
    if 'username' not in session or session['username'] != 'adime':
        return redirect(url_for('login'))

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM users WHERE username=%s", (username,))
        conn.commit()
    return redirect(url_for('admin_dashboard'))

@app.route('/signup')
def signup():
    return render_template('signup.html')

@app.route('/signup/business', methods=['GET', 'POST'])
def signup_business():
    if request.method == 'POST':
        username = request.form['username'].strip()  # remove leading/trailing spaces
        password = request.form['password'].strip()
        phone = request.form['phone']
        business_type = request.form['business_type']
        location = request.form['location']
        bio = request.form.get('bio', '')
        price = request.form.get('price', '')

        profile_pic_file = request.files.get('profile_pic')
        filename = ''
        if profile_pic_file and allowed_file(profile_pic_file.filename):
            filename = upload_to_cloudinary(profile_pic_file)

        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()

                # Check if the username already exists
                cursor.execute("SELECT 1 FROM users WHERE username = %s", (username,))
                if cursor.fetchone():
                    flash('Username is already taken.', 'danger')
                    return render_template('signup_business.html')  # Show same page with flash message

                # Insert into users table
                cursor.execute("""
                    INSERT INTO users 
                    (username, password, account_type, phone, business_type, location, bio, price, profile_pic) 
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (username, password, 'business', phone, business_type, location, bio, price, filename))

                # Insert into services and locations if new
                cursor.execute("INSERT INTO services (service_name) VALUES (%s) ON CONFLICT DO NOTHING", (business_type,))
                cursor.execute("INSERT INTO locations (location_name) VALUES (%s) ON CONFLICT DO NOTHING", (location,))
                conn.commit()

                return redirect(url_for('login'))

        except Exception as e:
            print(f"Error: {e}")
            flash('An error occurred during registration. Please try again.', 'danger')

    return render_template('signup_business.html')

@app.route('/signup/user', methods=['GET', 'POST'])
def signup_user():
    error = None
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password'].strip()
        phone = request.form['phone']
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
                return render_template('signup_user.html')  # Show same page with flash message
            else:
                try:
                    cursor.execute("INSERT INTO users (username, password, account_type, phone, profile_pic) VALUES (%s, %s, %s, %s, %s)", 
                                (username, password, 'user', phone, filename))
                    conn.commit()
                    return redirect(url_for('login'))
                except psycopg2.IntegrityError:
                    error = "An error occurred. Please try again."
    return render_template('signup_user.html', error=error)

@app.route('/profile')
@app.route('/profile/<username>')
def profile(username=None):
    if username is None:
        if 'username' not in session:
            return redirect(url_for('login'))
        username = session['username']

    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # User details
        cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
        user = cursor.fetchone()

        if not user:
            flash("User not found.")
            return redirect(url_for('home'))

        # Feedback for average rating
        cursor.execute("SELECT * FROM feedback WHERE to_user = %s", (username,))
        feedback = cursor.fetchall()

        # Rating calculations
        total_rating = sum([fb['rating'] for fb in feedback])
        rating_count = len(feedback)
        average_rating = round(total_rating / rating_count, 1) if rating_count > 0 else None

        # Check if the current user already rated
        has_rated = False
        if 'username' in session and session['username'] != username:
            cursor.execute("SELECT 1 FROM feedback WHERE to_user = %s AND from_user = %s", (username, session['username']))
            has_rated = cursor.fetchone() is not None

        # Reports
        cursor.execute("SELECT * FROM reports WHERE reported_user = %s", (username,))
        reports = cursor.fetchall()

        # Ownership and admin check
        is_owner = session.get('username') == username
        is_admin = session.get('username') == 'adime'

    return render_template('profile.html',
                           user=user,
                           feedback=feedback,
                           average_rating=average_rating,
                           rating_count=rating_count,
                           has_rated=has_rated,
                           reports=reports,
                           is_owner=is_owner,
                           is_admin=is_admin)

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

@app.route('/order', methods=['GET', 'POST'])
def place_order():
    if request.method == 'POST':
        service  = request.form['service']
        location = request.form['location']
        message  = request.form.get('message', 'No message provided')
        image    = request.files.get('image')

        # Save image
        image_path = None
        if image and allowed_file(image.filename):
            image_path = upload_to_cloudinary(image)
        # Open a new DB connection
        conn = get_db_connection()
        cur  = conn.cursor()

        # Insert order
        cur.execute(""" 
            INSERT INTO orders (owner_username, service, location, message)
            VALUES (%s, (SELECT id FROM services WHERE service_name = %s), %s, %s)
            RETURNING id
        """, (session['username'], service, location, message))
        order_id = cur.fetchone()[0]

        # Notify matching providers
        cur.execute(""" 
            SELECT username 
            FROM users 
            WHERE business_type = %s AND location = %s
        """, (service, location))
        
        for (provider,) in cur.fetchall():
            link = url_for('order_accept', order_id=order_id)

            # Insert notification into DB
            cur.execute(""" 
                INSERT INTO notifications (to_user, from_user, order_id, message, link, created_at, is_read)
                VALUES (%s, %s, %s, %s, %s, NOW(), false)
            """, (provider, session['username'], order_id, message, link))

            # 🔔 Get FCM token of the provider
            cur.execute("SELECT fcm_token FROM users WHERE username = %s", (provider,))
            token_result = cur.fetchone()
            if token_result and token_result[0]:
                send_push_notification(
                    token_result[0],
                    "New Order Available",
                    f"New order from {session['username']} for {service} in {location}"
                )

        conn.commit()
        cur.close()
        conn.close()

        flash("Order placed and providers notified.")
        return redirect(url_for('home'))

    # GET: show form
    conn = get_db_connection()
    cur  = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute("SELECT service_name FROM services ORDER BY service_name")
    services = cur.fetchall()

    cur.execute("SELECT location_name FROM locations ORDER BY location_name")
    locations = cur.fetchall()

    cur.close()
    conn.close()

    return render_template('order.html', services=services, locations=locations)

@app.route('/approve_provider/<int:order_id>', methods=['POST'])
def approve_provider(order_id):
    selected_provider = request.form.get('selected_provider')
    if not selected_provider:
        flash("No provider selected.")
        return redirect('/notifications')

    conn = get_db_connection()
    cur = conn.cursor()

    # Step 1: Mark approved provider
    cur.execute("""
        UPDATE order_acceptance SET final_selected = TRUE 
        WHERE order_id = %s AND provider_username = %s
    """, (order_id, selected_provider))

    # Step 2: Mark other providers as rejected
    cur.execute("""
        UPDATE order_acceptance SET accepted = FALSE 
        WHERE order_id = %s AND provider_username != %s
    """, (order_id, selected_provider))

    # Step 3: Notify approved provider
    cur.execute("""
        INSERT INTO notifications (to_user, from_user, order_id, message, created_at, is_read)
        VALUES (%s, %s, %s, %s, NOW(), FALSE)
    """, (selected_provider, session['username'], order_id, f"You have been approved for Order {order_id}!"))

    # 🔔 Send push notification to the approved provider
    cur.execute("SELECT fcm_token FROM users WHERE username = %s", (selected_provider,))
    token_result = cur.fetchone()
    if token_result and token_result[0]:
        send_push_notification(
            token_result[0],
            "Order Approved",
            f"You have been approved for Order {order_id}!"
        )

    # Step 4: Notify rejected providers
    cur.execute("""
        SELECT provider_username FROM order_acceptance 
        WHERE order_id = %s AND provider_username != %s
    """, (order_id, selected_provider))
    rejected = cur.fetchall()
    for r in rejected:
        cur.execute("""
            INSERT INTO notifications (to_user, from_user, order_id, message, created_at, is_read)
            VALUES (%s, %s, %s, %s, NOW(), FALSE)
        """, (r[0], session['username'], order_id, f"Sorry, you were not selected for Order {order_id}."))

    conn.commit()
    cur.close()
    conn.close()
    flash("Provider selection finalized.")
    return redirect('/home')

@app.route('/order_accept/<int:order_id>', methods=['POST'])
def order_accept(order_id):
    provider = session['username']

    conn = get_db_connection()
    cur = conn.cursor()

    # Accept the order
    cur.execute("""
        INSERT INTO order_acceptance (order_id, provider_username, accepted)
        VALUES (%s, %s, TRUE)
        ON CONFLICT (order_id, provider_username) DO NOTHING
    """, (order_id, provider))

    # Notify the owner
    cur.execute("SELECT owner_username FROM orders WHERE id = %s", (order_id,))
    owner = cur.fetchone()[0]
    cur.execute("""
        INSERT INTO notifications (to_user, from_user, order_id, message, created_at, is_read)
        VALUES (%s, %s, %s, %s, NOW(), FALSE)
    """, (owner, provider, order_id, f"{provider} accepted your order!"))

    # 🔔 Send push notification to the owner
    cur.execute("SELECT fcm_token FROM users WHERE username = %s", (owner,))
    token_result = cur.fetchone()
    if token_result and token_result[0]:
        send_push_notification(
            token_result[0],
            "Order Accepted",
            f"{provider} accepted your order!"
        )

    conn.commit()
    cur.close()
    conn.close()

    flash("You accepted the order!")
    return redirect(url_for('notifications'))

@app.route('/order_owners_view/<int:order_id>', methods=['GET', 'POST'])
def view_accepted_providers(order_id):
    conn = get_db_connection()
    cur = conn.cursor()

    if request.method == 'POST':
        selected = request.form['selected_provider']
        
        # Mark selected provider
        cur.execute("""
            UPDATE order_acceptance 
            SET final_selected = TRUE 
            WHERE order_id = %s AND provider_username = %s
        """, (order_id, selected))
        
        # Reject all others
        cur.execute("""
            UPDATE order_acceptance 
            SET accepted = FALSE 
            WHERE order_id = %s AND provider_username != %s
        """, (order_id, selected))

        # Notify selected provider
        message = f"You have been approved for Order {order_id}!"
        cur.execute("""
            INSERT INTO notifications (to_user, from_user, order_id, message, created_at, is_read)
            VALUES (%s, %s, %s, %s, NOW(), FALSE)
        """, (selected, session['username'], order_id, message))

        # Notify rejected providers
        cur.execute("""
            SELECT provider_username 
            FROM order_acceptance 
            WHERE order_id = %s AND provider_username != %s
        """, (order_id, selected))
        rejected_providers = [row[0] for row in cur.fetchall()]
        
        for rp in rejected_providers:
            message = f"Sorry, you were not selected for Order {order_id}."
            cur.execute("""
                INSERT INTO notifications (to_user, from_user, order_id, message, created_at, is_read)
                VALUES (%s, %s, %s, %s, NOW(), FALSE)
            """, (rp, session['username'], order_id, message))

        conn.commit()
        cur.close()
        conn.close()

        flash("Provider selection finalized.")
        return redirect('/home')
    return "Not Allowed", 405

@app.route('/notifications')
def notifications():
    if 'username' not in session:
        return redirect('/login')

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # Join with orders + add final selected provider (if any)
    cur.execute("""
    SELECT 
        n.id, n.from_user, n.order_id, o.owner_username, o.service, o.location, o.message AS order_message, 
        o.created_at AS order_created_at, n.message, n.created_at AS notif_created_at, n.is_read,
        (
            SELECT provider_username 
            FROM order_acceptance 
            WHERE order_id = n.order_id AND final_selected = TRUE
            LIMIT 1
        ) AS approved_provider
    FROM notifications n
    JOIN orders o ON o.id = n.order_id
    WHERE n.to_user = %s
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
            n.id, n.from_user, n.order_id, o.owner_username, o.service, o.location, o.message AS order_message, 
            o.created_at AS order_created_at, n.message, n.created_at AS notif_created_at, n.is_read,
            (
                SELECT provider_username 
                FROM order_acceptance 
                WHERE order_id = n.order_id AND final_selected = TRUE
                LIMIT 1
            ) AS approved_provider
        FROM notifications n
        JOIN orders o ON o.id = n.order_id
        WHERE n.to_user = %s
        ORDER BY n.id DESC
    """, (session['username'],))

    notes = cur.fetchall()
    cur.close()
    conn.close()

    return jsonify(notes)

@app.route('/firebase-messaging-sw.js')
def service_worker():
    return send_from_directory('static', 'firebase-messaging-sw.js')

@app.route('/register_token', methods=['POST'])
def register_token():
    if 'username' not in session:
        return jsonify({'error': 'Not logged in'}), 401

    data = request.get_json()
    token = data.get('token')

    if not token:
        return jsonify({'error': 'Token is required'}), 400

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET fcm_token=%s WHERE username=%s", (token, session['username']))
        conn.commit()

    return jsonify({'message': 'Token registered successfully'}), 200

@app.route('/save-token', methods=['POST'])
def save_token():
    data = request.json
    token = data.get('token')
    user = session.get('username')

    if token and user:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET fcm_token = %s WHERE username = %s", (token, user))
            conn.commit()
        return jsonify({"status": "success"}), 200
    return jsonify({"status": "error"}), 400

@app.route('/report/<username>', methods=['GET', 'POST'])
def report(username):
    if 'username' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        reason = request.form['reason']
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO reports (reported_user, reported_by, reason)
                VALUES (%s, %s, %s)
            """, (username, session['username'], reason))
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
            LEFT JOIN feedback f ON u.username = f.to_user
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
    from_user = session['username']

    conn = get_db_connection()
    cur = conn.cursor()

    # Prevent multiple ratings
    cur.execute("SELECT * FROM feedback WHERE to_user = %s AND from_user = %s", (username, from_user))
    if cur.fetchone():
        conn.close()
        flash("You have already rated this user.")
        return redirect(url_for('profile', username=username))

    # Insert feedback
    cur.execute(
        "INSERT INTO feedback (to_user, from_user, rating, comment) VALUES (%s, %s, %s, %s)",
        (username, from_user, rating, comment)
    )

    conn.commit()
    conn.close()

    flash("Rating submitted successfully.")
    return redirect(url_for('profile', username=username))

@app.route('/delete_rating/<username>', methods=['POST'])
def delete_rating(username):
    if 'username' not in session:
        return redirect(url_for('login'))

    current_user = session['username']

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("DELETE FROM feedback WHERE to_user = %s AND from_user = %s", (username, current_user))
    conn.commit()
    conn.close()

    flash("Your rating was deleted.")
    return redirect(url_for('profile', username=username))

@app.route('/logout')
def logout():
    session.pop('username', None)
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))


if __name__ == '__main__':
    init_db()
    app.run(debug=True)
