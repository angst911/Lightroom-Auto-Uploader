import os
import requests
import json
from lightroom import LightroomAPI
from dotenv import load_dotenv

load_dotenv()

def main():
    client_id = os.getenv("ADOBE_CLIENT_ID")
    client_secret = os.getenv("ADOBE_CLIENT_SECRET")
    refresh_token = os.getenv("ADOBE_REFRESH_TOKEN")

    if not all([client_id, client_secret, refresh_token]):
        print("Missing credentials in .env")
        return

    lr = LightroomAPI(client_id, client_secret, refresh_token)
    catalog_id = lr.get_catalog_id()
    album_name = os.getenv("ALBUM_NAME", "Server_Auto_Upload")

    print(f"Searching for all albums named '{album_name}'...")
    
    url = f"{lr.BASE_URL}/catalogs/{catalog_id}/albums"
    found_albums = []
    
    from urllib.parse import urljoin
    while url:
        response = requests.get(url, headers=lr._get_headers())
        data = lr._parse_lr_json(response.text)
        for album in data.get("resources", []):
            if album.get("payload", {}).get("name") == album_name:
                found_albums.append(album)
        
        next_href = data.get("links", {}).get("next", {}).get("href")
        url = urljoin(url, next_href) if next_href else None

    if not found_albums:
        print("No matching albums found.")
        return

    print(f"\nFound {len(found_albums)} albums:")
    for i, album in enumerate(found_albums):
        print(f"{i+1}. ID: {album['id']} (Created: {album['payload'].get('userCreated')})")

    confirm = input(f"\nDo you want to delete ALL {len(found_albums)} of these albums? (y/n): ").lower()
    if confirm == 'y':
        for album in found_albums:
            print(f"Deleting album {album['id']}...")
            del_url = f"{lr.BASE_URL}/catalogs/{catalog_id}/albums/{album['id']}"
            res = requests.delete(del_url, headers=lr._get_headers())
            if res.status_code in [200, 204]:
                print(f"Successfully deleted {album['id']}.")
            else:
                print(f"Failed to delete {album['id']}: {res.status_code}")
    else:
        print("Aborted.")

if __name__ == "__main__":
    main()
