#!/usr/bin/env python3
"""
Seed the first super-admin user.

Reads SUPER_ADMIN_EMAIL and SUPER_ADMIN_PASSWORD from .env file.
Run from project root: python scripts/seed_super_admin.py
"""

import sys
import os

# Add project root to path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

# Load .env file
from dotenv import load_dotenv
load_dotenv(os.path.join(project_root, ".env"))

import bcrypt as bcrypt_lib
from src.db import supabase
from src.config import settings


def hash_password(password: str) -> str:
    """Hash password using bcrypt directly."""
    return bcrypt_lib.hashpw(password.encode(), bcrypt_lib.gensalt()).decode()


def main():
    # Get credentials from environment
    email = os.getenv("SUPER_ADMIN_EMAIL")
    password = os.getenv("SUPER_ADMIN_PASSWORD")

    if not email or not password:
        print("Error: SUPER_ADMIN_EMAIL and SUPER_ADMIN_PASSWORD must be set in .env")
        sys.exit(1)

    # Check if super-admin already exists
    existing = supabase.table("super_admins").select("id").eq("email", email).execute()
    if existing.data:
        print(f"Super-admin with email '{email}' already exists.")
        sys.exit(0)

    # Hash password and insert
    password_hash = hash_password(password)

    result = supabase.table("super_admins").insert({
        "email": email,
        "password_hash": password_hash,
        "name": "Super Admin",
    }).execute()

    if result.data:
        super_admin = result.data[0]
        print(f"Created super-admin:")
        print(f"  ID: {super_admin['id']}")
        print(f"  Email: {super_admin['email']}")
        print(f"  Created: {super_admin['created_at']}")
    else:
        print("Error: Failed to create super-admin")
        sys.exit(1)


if __name__ == "__main__":
    main()
