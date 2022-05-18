from flask import Flask, render_template, redirect, request, g, session, flash
import requests
from models import db, connect_db, Category, User, Like
from forms import NewUser, LoginForm
from sqlalchemy.exc import IntegrityError

CURR_USER = "curr_user"

app = Flask(__name__)

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "postgresql:///boardgames"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SQLALCHEMY_ECHO"] = True
app.config["SECRET_KEY"] = "keep it secret, keep it safe"

connect_db(app)
db.create_all()

base_url = 'https://api.boardgameatlas.com/api'
client_id = 'Vk9QEJ2umU'

############################################################################################
# HELPER FUNCTIONS TO PULL LATER 
############################################################################################

def get_game_categories():
    """Get game category information and save to database table Category"""
    categories_resp = requests.get(f'{base_url}/game/categories?client_id={client_id}')
    json = categories_resp.json()
    categories = json['categories']

    for category in categories:
        category = Category(id = category['id'], name = category['name'])
        db.session.add(category)
    
    db.session.commit()

def get_category_names(games):
    """Accepts games JSON;
    Saves the category ids attributed to the game to a list;
    Queries the DB to get the names for categories by ID;
    returns a dictionary with the game's name as a key, and a list of category names as the value"""
    category_dict = {}
    for game in games:
        catlist = [category['id'] for category in game['categories'] if game['categories']]
        q = db.session.query(Category.name).filter(Category.id.in_(catlist)).all()
        category_names = [category[0] for category in q]
        category_dict[f"{game['name']}"] = category_names
    
    return category_dict
    

def main_request(base_url, endpoint, x):
    """function to cut down on repetition; 
    receives a base url and the endpoint for that url, 
    returns resp obj"""
    resp = requests.get(base_url + endpoint + f'&skip={x}')
    return resp


def parse_resp(resp):
    """parses the resp as JSON, 
    and returns the games object from the parsed resp"""
    json = resp.json()
    games = json['games']
    return games


def get_count_of_resp(resp):
    """Return the number of game objects in the response"""
    json = resp.json()
    return json['count']

############################################################################################
# SEARCH ROUTES
############################################################################################

@app.route('/games/top_games')
def show_homepage():
    """Get game data from BGA based on its rank and display in groups of 12"""

    games = parse_resp(main_request(base_url, f'/search/?order_by=rank&limit=12&client_id={client_id}', 0))
    
    category_dict = get_category_names(games)

    likes = g.user.liked_games
    game_ids_list = [game.game_id for game in likes]

    return render_template('search_results.html', games=games, category_dict=category_dict, game_ids_list=game_ids_list, type='Rated')


@app.route('/games/<category_name>')
def show_games_in_category(category_name):
    """Show top 12 games in a specific category"""

    category = Category.query.filter_by(name=category_name).first()
    
    resp = main_request(base_url, f'/search/?categories={category.id}&limit=12&order_by=rank&client_id={client_id}', 0)

    ### working here on maybe paginating search results?
    print(get_count_of_resp(resp))
    for x in range(get_count_of_resp(resp)):
        print(x)

    games = parse_resp(resp)
    category_dict = get_category_names(games)

    return render_template('search_results.html', games=games, category_dict=category_dict, type=category_name)


@app.route('/games/player_count_<int:num>')
def show_games_by_player_count(num):
    """Show top ranked games based on minimum number of players"""

    games = parse_resp(main_request(base_url, f'/search/?min_players={num}&order_by=rank&limit=12&client_id={client_id}', 0))

    category_dict = get_category_names(games)

    return render_template('search_results.html', games=games, category_dict=category_dict, type=f'{num}+ Players')


@app.route('/games/player_min_<int:min_num>&player_max_<int:max_num>')
def show_games_by_player_range(min_num, max_num):
    """Show top ranked games based on min and max player range"""

    games = parse_resp(main_request(base_url, f'/search/?min_players={min_num}&max_players={max_num}&limit=12&order_by=rank&client_id={client_id}', 0))

    category_dict = get_category_names(games)

    return render_template('search_results.html', games=games, category_dict=category_dict, type=f'{min_num}-{max_num} Players')


@app.route('/games/name')
def search_games_by_name():

    query = request.args.get('query')

    if query == '':
        games = parse_resp(main_request(base_url, f'/search?limit=12&client_id={client_id}', 0))
    else:
        games = parse_resp(main_request(base_url, f'/search/?name={query}&fuzzy_match=true&limit=12&client_id={client_id}', 0))
    
    category_dict = get_category_names(games)

    return render_template('search_results.html', games=games, category_dict=category_dict, type=f'{query}')


############################################################################################
# DISPLAY ROUTES
############################################################################################
@app.route('/')
def home():
    """If not logged in, render login page;
    if logged in, redirect to /top_games"""
    return redirect('/games/top_games')


@app.route('/games/game/<game_id>')
def show_game_page(game_id):
    """Show info page for individual game"""
    
    games = parse_resp(main_request(base_url, f'/search/?ids={game_id}&client_id={client_id}', 0))
    
    category_dict = get_category_names(games)
    game = games[0]

    return render_template('game_page.html', game=game, category_dict=category_dict)


@app.route('/users/profile/<int:user_id>')
def show_user_page(user_id):
    user = User.query.get_or_404(user_id)

    game_ids_list = [game.game_id for game in user.liked_games]

    game_ids = ','.join([str(id) for id in game_ids_list])

    games = parse_resp(main_request(base_url, f'/search/?ids={game_ids}&client_id={client_id}', 0))

    return render_template('show_user.html', user=user, games=games)


@app.route('/users/like_game/<game_id>', methods=["POST"])
def like_game(game_id):
    """Logged in user may like or unlike a game"""
    if not g.user:
        flash("Access unauthorized.", "danger")
        return redirect("/")
    
    games = parse_resp(main_request(base_url, f'/search/?ids={game_id}&client_id={client_id}', 0))
    game = games[0]
    game_id = game['id']

    likes = g.user.liked_games
    game_ids_list = [game.game_id for game in likes]

    if game_id in game_ids_list:
        Like.query.filter_by(game_id=game_id, user_id=g.user.id).delete()
    else:
        liked_game = Like(user_id=g.user.id, game_id=game_id)
        db.session.add(liked_game)

    db.session.commit()

    return redirect(f'/users/profile/{g.user.id}')


############################################################################################
# LOGIN / LOGOUT and AUTHENTICATION ROUTES
############################################################################################

@app.before_request
def add_user_to_g():
    """If the user is logged in, add them to g"""

    if CURR_USER in session:
        g.user = User.query.get(session[CURR_USER])
    else:
        g.user = None


@app.route('/register', methods=['GET', 'POST'])
def signup():
    """Handle user registration; create user and add to DB, then redirect to home page"""

    form = NewUser()

    if form.validate_on_submit():
            user = User.register(
                username=form.username.data,
                password=form.password.data,
                email=form.email.data
            )
            db.session.commit()
            # add new user to g, and set session
            session[CURR_USER] = user.id
            return redirect('/games/top_games')

    else:
        return render_template('register.html', form=form)


@app.route('/login', methods=['GET', 'POST'])
def login_user():
    """Login a registered user"""

    form = LoginForm()

    if form.validate_on_submit():
        user = User.authenticate(form.username.data, form.password.data)

        if user:
            session[CURR_USER] = user.id
            return redirect('/games/top_games')

    return render_template('login_user.html', form=form)


@app.route('/logout')
def logout_user():
    """Logout a registered user"""
    if CURR_USER in session:
        del session[CURR_USER]
    
    return redirect('/games/top_games')

