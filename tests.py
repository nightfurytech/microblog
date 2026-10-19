#!/usr/bin/env python
from datetime import datetime, timezone, timedelta
import unittest
import sqlalchemy as sa
from app import create_app, db
from app.models import User, Post
from config import Config


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite://'
    ELASTICSEARCH_URL = None


class UserModelCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig)
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_password_hashing(self):
        u = User(username='susan', email='susan@example.com')
        u.set_password('cat')
        self.assertFalse(u.check_password('dog'))
        self.assertTrue(u.check_password('cat'))

    def test_avatar(self):
        u = User(username='john', email='john@example.com')
        self.assertEqual(u.avatar(128), ('https://www.gravatar.com/avatar/'
                                         'd4c74594d841139328695756648b6bd6'
                                         '?d=identicon&s=128'))

    def test_follow(self):
        u1 = User(username='john', email='john@example.com')
        u2 = User(username='susan', email='susan@example.com')
        db.session.add(u1)
        db.session.add(u2)
        db.session.commit()
        following = db.session.scalars(u1.following.select()).all()
        followers = db.session.scalars(u2.followers.select()).all()
        self.assertEqual(following, [])
        self.assertEqual(followers, [])

        u1.follow(u2)
        db.session.commit()
        self.assertTrue(u1.is_following(u2))
        self.assertEqual(u1.following_count(), 1)
        self.assertEqual(u2.followers_count(), 1)
        u1_following = db.session.scalars(u1.following.select()).all()
        u2_followers = db.session.scalars(u2.followers.select()).all()
        self.assertEqual(u1_following[0].username, 'susan')
        self.assertEqual(u2_followers[0].username, 'john')

        u1.unfollow(u2)
        db.session.commit()
        self.assertFalse(u1.is_following(u2))
        self.assertEqual(u1.following_count(), 0)
        self.assertEqual(u2.followers_count(), 0)

    def test_follow_posts(self):
        # create four users
        u1 = User(username='john', email='john@example.com')
        u2 = User(username='susan', email='susan@example.com')
        u3 = User(username='mary', email='mary@example.com')
        u4 = User(username='david', email='david@example.com')
        db.session.add_all([u1, u2, u3, u4])

        # create four posts
        now = datetime.now(timezone.utc)
        p1 = Post(body="post from john", author=u1,
                  timestamp=now + timedelta(seconds=1))
        p2 = Post(body="post from susan", author=u2,
                  timestamp=now + timedelta(seconds=4))
        p3 = Post(body="post from mary", author=u3,
                  timestamp=now + timedelta(seconds=3))
        p4 = Post(body="post from david", author=u4,
                  timestamp=now + timedelta(seconds=2))
        db.session.add_all([p1, p2, p3, p4])
        db.session.commit()

        # setup the followers
        u1.follow(u2)  # john follows susan
        u1.follow(u4)  # john follows david
        u2.follow(u3)  # susan follows mary
        u3.follow(u4)  # mary follows david
        db.session.commit()

        # check the following posts of each user
        f1 = db.session.scalars(u1.following_posts()).all()
        f2 = db.session.scalars(u2.following_posts()).all()
        f3 = db.session.scalars(u3.following_posts()).all()
        f4 = db.session.scalars(u4.following_posts()).all()
        self.assertEqual(f1, [p2, p4, p1])
        self.assertEqual(f2, [p2, p3])
        self.assertEqual(f3, [p3, p4])
        self.assertEqual(f4, [p4])


class APIPostsCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig)
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def _create_user(self, username):
        user = User(username=username, email=f'{username}@example.com')
        user.set_password('cat')
        db.session.add(user)
        db.session.commit()
        return user

    def _auth_headers(self, user):
        token = user.get_token()
        db.session.commit()
        return {'Authorization': f'Bearer {token}'}

    def _add_post(self, user, body, minutes_ago=0):
        timestamp = datetime.now(timezone.utc) - timedelta(
            minutes=minutes_ago)
        db.session.add(Post(body=body, author=user, timestamp=timestamp))
        db.session.commit()

    def test_get_post(self):
        user = self._create_user('john')
        self._add_post(user, 'hello world')
        post = db.session.scalars(sa.select(Post)).first()
        response = self.client.get(f'/api/posts/{post.id}',
                                   headers=self._auth_headers(user))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['body'], 'hello world')

    def test_get_post_requires_auth(self):
        user = self._create_user('john')
        self._add_post(user, 'hello world')
        post = db.session.scalars(sa.select(Post)).first()
        response = self.client.get(f'/api/posts/{post.id}')
        self.assertEqual(response.status_code, 401)

    def test_user_posts_require_auth(self):
        user = self._create_user('john')
        self._add_post(user, 'first')
        response = self.client.get(f'/api/users/{user.id}/posts')
        self.assertEqual(response.status_code, 401)

    def test_user_posts_unknown_user(self):
        user = self._create_user('john')
        response = self.client.get('/api/users/999/posts',
                                   headers=self._auth_headers(user))
        self.assertEqual(response.status_code, 404)

    def test_user_posts_author_has_no_email(self):
        user = self._create_user('john')
        self._add_post(user, 'hello world')
        response = self.client.get(f'/api/users/{user.id}/posts',
                                   headers=self._auth_headers(user))
        json = response.get_json()
        self.assertEqual(json['items'][0]['author']['username'], 'john')
        self.assertNotIn('email', json['items'][0]['author'])

    def test_user_posts_pagination(self):
        user = self._create_user('john')
        for i in range(12):
            self._add_post(user, f'post {i}', minutes_ago=i)
        response = self.client.get(
            f'/api/users/{user.id}/posts?per_page=5&page=2',
            headers=self._auth_headers(user))
        json = response.get_json()
        bodies = [item['body'] for item in json['items']]
        self.assertEqual(bodies, ['post 5', 'post 6', 'post 7',
                                  'post 8', 'post 9'])
        self.assertEqual(json['_meta']['total_pages'], 3)
        self.assertIsNotNone(json['_links']['next'])
        self.assertIsNotNone(json['_links']['prev'])

    def test_user_posts_per_page_is_capped(self):
        user = self._create_user('john')
        self._add_post(user, 'hello world')
        response = self.client.get(
            f'/api/users/{user.id}/posts?per_page=1000',
            headers=self._auth_headers(user))
        self.assertEqual(response.get_json()['_meta']['per_page'], 100)

    def test_feed(self):
        john = self._create_user('john')
        susan = self._create_user('susan')
        mary = self._create_user('mary')
        john.follow(susan)
        db.session.commit()
        self._add_post(susan, 'susan 1', minutes_ago=10)
        self._add_post(john, 'john 1', minutes_ago=5)
        self._add_post(mary, 'mary 1', minutes_ago=2)
        self._add_post(susan, 'susan 2', minutes_ago=1)
        response = self.client.get('/api/posts/feed',
                                   headers=self._auth_headers(john))
        self.assertEqual(response.status_code, 200)
        bodies = [item['body'] for item in response.get_json()['items']]
        self.assertEqual(bodies, ['susan 2', 'john 1', 'susan 1'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
