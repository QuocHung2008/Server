api_keys_cache = {}

async def load_api_keys():
    global api_keys_cache
    api_keys_cache.clear()
    
    print("Loading API keys into cache...")
    from app.database import pool
    if pool is None:
        print("Error: DB Pool not initialized!")
        return
        
    async with pool.acquire() as conn:
        records = await conn.fetch('''
            SELECT key_hash, is_active FROM api_keys
        ''')
        for record in records:
            api_keys_cache[record['key_hash']] = record['is_active']
            
    print(f"Loaded {len(api_keys_cache)} API keys.")

def is_valid_api_key(key: str) -> bool:
    # simple validation check logic 
    import hashlib
    key_hash = hashlib.sha256(key.encode()).hexdigest()
    return api_keys_cache.get(key_hash, False)
