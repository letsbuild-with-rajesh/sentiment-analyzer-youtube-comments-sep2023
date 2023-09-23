from flask import Flask, render_template, request
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from transformers import pipeline
from apiclient.discovery import build
from datetime import datetime
from os import environ, path
import re

# Create app
app = Flask(__name__)

# Setup DB
basedir = path.abspath(path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + path.join(basedir, 'app.db')

# Create DB connection and Migration object
db = SQLAlchemy(app)
migrate = Migrate(app, db)

# Video Model
class Video(db.Model):
  id = db.Column(db.Integer, primary_key=True)
  url = db.Column(db.String(100), unique=True, nullable=False)
  title = db.Column(db.String(20), unique=False, nullable=False)
  score = db.Column(db.Float, unique=False, nullable=False)
  sentiment = db.Column(db.String(8), unique=False, nullable=False)
  created_at = db.Column(db.DateTime, default=datetime.now)

@app.route("/", methods=['GET'])
def index():
  return render_template('index.html')

def get_videoid_from_url(url):
  videoIdSearch = re.search("(?<=v=)([0-9A-Za-z_-]{11})", url) or re.search("(?<=\/)([0-9A-Za-z_-]{11})", url)
  if videoIdSearch is None:
    return None
  return videoIdSearch.group()

def get_video_title_from_youtube(youtube, videoId):
  video_response = youtube.videos().list(part='snippet',id=videoId).execute()
  return video_response['items'][0]['snippet']['title']

def get_video_comments_from_youtube(youtube, videoId):
  response = youtube.commentThreads().list(part='snippet',videoId=videoId).execute()
  video_comments = []
  for item in response["items"]:
    video_comment = item["snippet"]["topLevelComment"]["snippet"]["textOriginal"]
    video_comments.append(video_comment)
  return video_comments

def get_segregated_comments_and_stats(video_comments, sentiment_analysis_comments):
  overall_score = 0
  positive_comments = []
  negative_comments = []
  neutral_comments = []
  for id, video_comment in enumerate(video_comments):
    label = sentiment_analysis_comments[id]['label']
    score = sentiment_analysis_comments[id]['score']

		# Calculate overall score in terms of positivity
    if label == 'POSITIVE':
      overall_score = overall_score + score
    else:
      overall_score = overall_score + (1 - score)

		# Separate positive, negative and neutral comments
    if score > 0.4 and score < 0.7:
      neutral_comments.append({'comment': video_comment, 'score': score})
    elif label == 'POSITIVE':
      positive_comments.append({'comment': video_comment, 'score': score})
    else:
      negative_comments.append({'comment': video_comment, 'score': score})

  positive_comments = sorted(positive_comments, key=lambda x: x['score'], reverse=True)[:5]
  negative_comments = sorted(negative_comments, key=lambda x: x['score'], reverse=True)[:5]
  # Find closest value to 5 for more neutral comments
  neutral_comments = sorted(neutral_comments, key=lambda x: abs(5 - x['score']), reverse=True)[:5]

  overall_score = round((overall_score / len(video_comments)), 2)

	# Knowing the overall sentiment
  overall_sentiment = ''
  if overall_score > 0.4 and overall_score < 0.7:
    overall_sentiment = 'NEUTRAL'
  elif overall_score > 0.7:
    overall_sentiment = 'POSITIVE'
  else:
    overall_sentiment = 'NEGATIVE'

  return {
    'positive': positive_comments,
		'negative': negative_comments,
		'neutral': neutral_comments,
		'overall_sentiment': overall_sentiment,
		'overall_score': overall_score
	}

@app.route("/evaluate_sentiment", methods=['POST'])
def evaluate_sentiment():
  url = request.form['url']
  video_url = url.replace("watch?v=", "v/")

	# Init
  GCP_API_KEY = environ.get('GCP_API_KEY')
  youtube = build('youtube','v3', developerKey=GCP_API_KEY)

	# Get Video Details
  videoId = get_videoid_from_url(video_url)
  if videoId is None:
    return "Invalid video url"
  video_title = get_video_title_from_youtube(youtube, videoId)
  video_comments = get_video_comments_from_youtube(youtube, videoId)

	# Learn sentiments from transformers pipeline
  sentiment_analysis_pipeline = pipeline("sentiment-analysis")
  sentiment_analysis_comments = sentiment_analysis_pipeline(video_comments)

	# Get segregated comments and stats
  comments = get_segregated_comments_and_stats(video_comments, sentiment_analysis_comments)

	# Save video details if exists otherwise update the sentiment and score
  video = Video.query.filter_by(url=video_url).first()
  if video is None:
    video = Video(url=video_url, title=video_title, score=comments['overall_score'], sentiment=comments['overall_sentiment'])
  else:
    video.score = comments['overall_score']
    video.sentiment = comments['overall_sentiment']
  db.session.add(video)
  db.session.commit()

  return render_template('sentiment_visualizer.html', url=video_url, comments=comments)

@app.route("/recents", methods=['GET', 'DELETE'])
def recents():
  if request.method == 'GET':
    recent_videos = Video.query.order_by(Video.created_at.desc()).all()
    videos = []
    for video in recent_videos:
      videos.append({
      	'url': video.url,
        'title': video.title,
        'sentiment': video.sentiment,
        'score': video.score,
      })
    return render_template('recents.html', videos=videos)
  elif request.method == 'DELETE':
    Video.query.delete()
    db.session.commit()
    return { 'success': True }

if __name__ == "__main__":
  app.run(debug=True)
