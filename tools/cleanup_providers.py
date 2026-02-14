"""One-time cleanup script to remove provider records with date-like names."""
from database import init_db, cleanup_providers_date_like

if __name__ == '__main__':
    init_db()
    candidates = cleanup_providers_date_like(delete=False)
    if not candidates:
        print("No date-like provider names found.")
    else:
        print(f"Found {len(candidates)} candidates:")
        for c in candidates:
            print(f" - {c['id']}: {c['name']}")
        confirm = input('Delete these providers? (yes/NO): ')
        if confirm.lower() in ('yes', 'y'):
            cleanup_providers_date_like(delete=True)
            print('Deleted candidates.')
        else:
            print('No changes made.')
