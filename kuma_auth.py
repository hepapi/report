#!/usr/bin/env python3
"""
kuma_ui.py icin basit, dosya tabanli kullanici deposu.

Kullanicilar bir JSON dosyasinda {"kullanici_adi": "hash", ...} seklinde
saklanir - sifreler asla duz metin olarak yazilmaz (werkzeug'un
generate_password_hash/check_password_hash'i kullanilir).

Kullanici eklemek/silmek icin kuma_ui.py'nin --add-user / --remove-user /
--list-users komutlarini kullanin (bu modul dogrudan CLI olarak da
calisir, bkz. altta).
"""
import json
from pathlib import Path

from werkzeug.security import check_password_hash, generate_password_hash

DEFAULT_USERS_FILE = 'users.json'


def load_users(path=DEFAULT_USERS_FILE):
    p = Path(path)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def save_users(path, users):
    Path(path).write_text(json.dumps(users, indent=2, ensure_ascii=False) + '\n')


def add_user(path, username, password):
    users = load_users(path)
    users[username] = generate_password_hash(password)
    save_users(path, users)
    return users


def remove_user(path, username):
    users = load_users(path)
    existed = users.pop(username, None) is not None
    save_users(path, users)
    return existed


def verify(users, username, password):
    """Kullanici adi/sifre dogru mu? Zamanlama saldirilarina karsi,
    kullanici bulunamasa bile bir hash dogrulamasi calistiriyoruz."""
    stored_hash = users.get(username)
    if not stored_hash:
        check_password_hash(generate_password_hash('dummy'), password)
        return False
    return check_password_hash(stored_hash, password)


if __name__ == '__main__':
    import argparse
    import getpass

    p = argparse.ArgumentParser(description='kuma_ui.py kullanici yonetimi')
    p.add_argument('--users-file', default=DEFAULT_USERS_FILE)
    sub = p.add_subparsers(dest='cmd', required=True)

    add_p = sub.add_parser('add', help='Kullanici ekle/sifresini guncelle')
    add_p.add_argument('username')

    rm_p = sub.add_parser('remove', help='Kullanici sil')
    rm_p.add_argument('username')

    sub.add_parser('list', help='Kullanicilari listele')

    args = p.parse_args()

    if args.cmd == 'add':
        pw = getpass.getpass(f"'{args.username}' icin sifre: ")
        pw2 = getpass.getpass('Sifre (tekrar): ')
        if pw != pw2:
            print('✗ Sifreler eslesmedi.')
            raise SystemExit(1)
        if not pw:
            print('✗ Bos sifre olmaz.')
            raise SystemExit(1)
        add_user(args.users_file, args.username, pw)
        print(f"✓ '{args.username}' eklendi/guncellendi ({args.users_file}).")
    elif args.cmd == 'remove':
        if remove_user(args.users_file, args.username):
            print(f"✓ '{args.username}' silindi.")
        else:
            print(f"'{args.username}' zaten yoktu.")
    elif args.cmd == 'list':
        users = load_users(args.users_file)
        if not users:
            print('Hic kullanici yok.')
        else:
            print(f'{len(users)} kullanici:')
            for u in sorted(users):
                print(f'  - {u}')
