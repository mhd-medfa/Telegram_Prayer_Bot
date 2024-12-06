import os
from typing import List
from dataclasses import dataclass

import firebase_admin
from firebase_admin import firestore
from firebase_admin import credentials
from firebase_admin import db

from config import settings


@dataclass
class User:
    id: str
    active: bool


class DBHelper:
    def __init__(self):
        cred = credentials.Certificate(settings.CREDENTIALS_FILE)
        app = firebase_admin.initialize_app(cred)
        db = firestore.client(app)
        self.collection = db.collection("users")

    def add_user(self, user_id: str):
        self.collection.add({'active': True}, document_id=str(user_id))

    def get_user(self, user_id: str) -> User:
        user_dict = self.collection.document(str(user_id)).get()
        return None if not user_dict.exists else User(user_id, user_dict.get('active'))

    def set_active(self, user_id: str, active: bool):
        self.collection.document(str(user_id)).update({'active': active})

    def delete_user(self, user_id: str):
        self.collection.document(str(user_id)).delete()

    def list_users(self) -> List[User]:
        users = self.collection.get()
        return [User(user.id, user.get('active')) for user in users]
