from flask import request
from app import db
from app.models import User, Post
from app.api import bp
from app.api.auth import token_auth


@bp.route('/posts/<int:id>', methods=['GET'])
@token_auth.login_required
def get_post(id):
    return db.get_or_404(Post, id).to_dict()


@bp.route('/users/<int:id>/posts', methods=['GET'])
def get_user_posts(id):
    user = db.get_or_404(User, id)
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)
    query = user.posts.select().order_by(Post.timestamp.desc())
    return Post.to_collection_dict(query, page, per_page,
                                   'api.get_user_posts', id=id)


@bp.route('/posts/feed', methods=['GET'])
@token_auth.login_required
def get_feed():
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 10, type=int), 100)
    query = token_auth.current_user().following_posts()
    return Post.to_collection_dict(query, page, per_page, 'api.get_feed')
