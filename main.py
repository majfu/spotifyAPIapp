import json

from flask import Flask, redirect, jsonify, session, request, render_template, url_for
import urllib.parse
import requests
from datetime import datetime
import links
import os
from dotenv import load_dotenv, dotenv_values


load_dotenv()
app = Flask(__name__)
app.secret_key = '1298379-12hjh-12681wghd'
REDIRECT_URI = 'http://localhost:5000/callback'


@app.route('/')
def index():
    return "Hello! <a href='/login'>Login with Spotify</a>"



@app.route('/login')
def login():
    scope = 'user-read-private user-read-email playlist-modify-public playlist-modify-private user-top-read'

    params = {
        'client_id': os.getenv("CLIENT_ID"),
        'response_type': 'code',
        'scope': scope,
        'redirect_uri': REDIRECT_URI,
        'show_dialog': True #log in every time
    }

    auth_url = f"{links.AUTH_URL}?{urllib.parse.urlencode(params)}"

    return redirect(auth_url)

@app.route('/callback')
def callback():
    if 'error' in request.args:
        return jsonify({"error": request.args['error']})

    if 'code' in request.args:
        req_body = {
            'code': request.args['code'],
            'grant_type': 'authorization_code',
            'redirect_uri': REDIRECT_URI,
            'client_id': os.getenv("CLIENT_ID"),
            'client_secret': os.getenv("CLIENT_SECRET")
        }

        response = requests.post(links.TOKEN_URL, data=req_body)
        token_info = response.json()

        session['access_token'] = token_info['access_token']
        session['refresh_token'] = token_info['refresh_token']
        session['expires_at'] = datetime.now().timestamp() + token_info['expires_in']

        return redirect('/home')

@app.route('/home')
def home():
    s='''
    <a href='/playlists'>Lists of playlists on your account</a>
    <br>
    <a href='/geturl'>Get new recommended playlists</a>
    <br>
    <a href='/suggestions'>Get new music suggestions</a>
    '''
    return s





@app.route('/playlists')
def get_playlists():
    if 'access_token' not in session:
        return redirect('/login')

    if datetime.now().timestamp() > session['expires_at']:
        return redirect('/refresh_token')

    headers = {
        'Authorization': f"Bearer {session['access_token']}"
    }

    response = requests.get(links.API_BASE_URL + 'me/playlists', headers=headers)
    playlists = response.json()

    playlist_titles = list(map(lambda i: i['name'], playlists['items']))[:-1]
    playlist_hrefs = list(map(lambda i: i['tracks']['href'], playlists['items']))
    playlist_songs = []

    for href in playlist_hrefs:
        response = requests.get(href, headers=headers)
        href_items = response.json() #each element in href_items["items"] is info about one song
        songs = list(map(lambda i: i["track"]["name"], href_items["items"]))
        playlist_songs.append(songs)

    zipped = list(zip(playlist_titles, playlist_songs))

    file_name = "example.txt"
    #txt = str(zipped).encode("cp1252", errors="replace").decode("cp1252")

    with open(file_name, 'w') as f:
        json.dump(zipped, f, indent=3)
        f.close()

    zipped_html = ''
    for item in zipped:
        zipped_html += f'{item[0]}:<br>'
        for sub_item in item[1]:
            zipped_html += f'&emsp;{sub_item}<br>'
        zipped_html += '<br>'


    return f'''<a href='/home'>Home</a>
    <br>
    <a>{zipped_html}</a>'''




@app.route('/geturl', methods=['GET', 'POST'])
def get_url():
    if request.method == 'GET':
        return render_template('get_url_html.html')
    url = request.form.get('url')
    return redirect(url_for('get_recommendations', original_playlist_id=url[34:56]))


@app.route('/suggestions')
def get_suggestions():
    if 'access_token' not in session:
        return redirect('/login')

    if datetime.now().timestamp() > session['expires_at']:
        return redirect('/refresh_token')

    headers = {
        'Authorization': f"Bearer {session['access_token']}"
    }

    data = json.dumps({})

    response = requests.get(links.API_BASE_URL + 'me/top/artists?limit=15&time_range=long_term', headers=headers)
    top_artists = response.json()["items"] #list of dictionaries

    artists_id_list = [d["id"] for d in top_artists]

    all_related_artists = []
    for artist_id in artists_id_list:
        response = requests.get(links.API_BASE_URL + f'artists/{artist_id}/related-artists', headers=headers)
        related_artists = response.json()["artists"] #list of dictionaries

        all_related_artists.extend(related_artists)

    related_artists_id_list = [d["id"] for d in all_related_artists]

    track_uris = [] #list of uris
    for artist in related_artists_id_list:
        response = requests.get(links.API_BASE_URL + f'artists/{artist}/top-tracks', headers=headers)
        top_tracks = response.json()["tracks"] #list of dictionaries
        for i in range(3):
            track_uris.append(top_tracks[i]["uri"])


    response = requests.get(links.API_BASE_URL + "me", headers=headers)
    user_id = response.json()['id']

    new_playlist_name = f"Suggested tracks"

    req_body = json.dumps({
        'name': new_playlist_name,
    })

    response = requests.post(links.API_BASE_URL + f'users/{user_id}/playlists',
                             data=req_body, headers=headers)
    resp = response.json()

    new_playlist_id = resp['id']

    #at most 100 items can be added to playlist in one request
    a=0
    for i in range(100, len(track_uris), 100):

        req_body = json.dumps({
            "uris" : track_uris[a:i]
        })
        response = requests.post(links.API_BASE_URL + f'playlists/{new_playlist_id}/tracks',
                                 data=req_body, headers=headers)
        a = i

    if a < len(track_uris):
        req_body = json.dumps({
            "uris": track_uris[a:]
        })
        response = requests.post(links.API_BASE_URL + f'playlists/{new_playlist_id}/tracks', data=req_body, headers=headers)

    return f"<a>Created playlist with suggestions. Playlist ID: {new_playlist_id}</a><br><a href='/home'>Home</a>"


@app.route('/recommendations/<original_playlist_id>')
def get_recommendations(original_playlist_id):
    '''
            #from this playlist's id we get: a list of its songs' spotify IDs, a list of its songs' URIs
            #then we iterate over the IDs list to get e.g., 5 recommendations
                #we get recommendations' URIs
                #if a recommendation URI is neither in the original nor in the new playlists' lists of URIs
                    #it is added to the new playlist's list of URIs
            #new playlist is created
            #we iterate over the new playlist's list of URIs to add these songs to the newly created playlist

            '''

    if 'access_token' not in session:
        return redirect('/login')

    if datetime.now().timestamp() > session['expires_at']:
        return redirect('/refresh_token')



    headers = {
        'Authorization': f"Bearer {session['access_token']}"
    }

    response = requests.get(links.API_BASE_URL + "me", headers=headers)
    user_id = response.json()['id']

    response = requests.get(links.API_BASE_URL + f'playlists/{original_playlist_id}/tracks', headers=headers)
    original_playlist_tracks = response.json()

    original_track_uris = [track['track']['uri'] for track in original_playlist_tracks['items']]
    original_track_ids = [track['track']['id'] for track in original_playlist_tracks['items']]

    recommendations = []
    for track_id in original_track_ids:
        try:
            response_recommendations = requests.get(links.API_BASE_URL + f'recommendations?limit=5&seed_tracks={track_id}',
                                                    headers=headers)
            recommendations_data = response_recommendations.json()['tracks']
            recommendations.append(recommendations_data)
        except Exception as e:
            print("Error:", e)
            continue

    if len(recommendations) == 0:
        return  '''<a>Error</a>
        <br>
        <a href='/home'>Home</a>
        '''

    unique_recommendations = []
    for lst in recommendations:
        for recommendation in lst:
            if recommendation['uri'] not in original_track_uris and recommendation['uri'] not in unique_recommendations:
                unique_recommendations.append(recommendation['uri'])

            if len(unique_recommendations) >= 100:
                break

    new_playlist_name = f"Recommended from {original_playlist_id}"

    req_body = json.dumps({
        'name': new_playlist_name,
    })

    response = requests.post(links.API_BASE_URL + f'users/{user_id}/playlists',
                             data=req_body, headers=headers)
    resp = response.json()


    try:
        new_playlist_id = resp['id']
    except KeyError:
        return '''<a>Error: Couldn't create new playlist.</a>
        <br>
        <a href='/home'>Home</a>
        '''

    a = 0
    for i in range(100, len(unique_recommendations), 100):
        req_body = json.dumps({
            "uris": unique_recommendations[a:i]
        })
        response = requests.post(links.API_BASE_URL + f'playlists/{new_playlist_id}/tracks',
                                 data=req_body, headers=headers)
        a = i

    if a < len(unique_recommendations):
        req_body = json.dumps({
            "uris": unique_recommendations[a:]
        })
        response = requests.post(links.API_BASE_URL + f'playlists/{new_playlist_id}/tracks', data=req_body,
                                 headers=headers)

    return f"<a>New playlist created with recommendations from {original_playlist_id}. Playlist ID: {new_playlist_id}</a><br><a href='/home'>Home</a>"




@app.route('/refresh_token')
def refresh_token():
    if 'refresh_token' not in session:
        return redirect('/login')

    if datetime.now().timestamp() > session['expires_at']:
        req_body = {
            'grant_type': 'refresh_token',
            'refresh_token': session['refresh_token'],
            'client_id': os.getenv("CLIENT_ID"),
            'client_secret': os.getenv("CLIENT_SECRET")
        }

        response = requests.post(links.TOKEN_URL, data=req_body)
        new_token_info = response.json()

        session['access_token'] = new_token_info['access_token']
        session['expires_at'] = datetime.now().timestamp() + new_token_info['expires_in']

        return  redirect('/home')

if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True)
