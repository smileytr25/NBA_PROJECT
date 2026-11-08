import time 
import uuid 
import atexit 
import os 
import json 

class RateLimiter():
    def __init__(self, limit=15, shelf_life=60, persistence_dir="./rate_limiter_cache", persistence_file="state.json", persist=True):
        self.limit = limit 
        self.shelf_life = shelf_life 
        self.shelf = {}
        self.persistence_dir = persistence_dir 
        self.persistence_file = persistence_file 

        if persist == True:
            self.load_persisted_state()
            atexit.register(self.persist_state)

    def request_count(self):
        self.check_shelf_expirations() 

        return len(self.shelf)

    def check_shelf_expirations(self):
        current = time.time() 

        reqs_to_remove = []
        for req, inception in self.shelf.items():
            if current - inception >= self.shelf_life:
                reqs_to_remove.append(req)

        for req in reqs_to_remove:
            del self.shelf[req]

    def wait_time(self):
        current = time.time() 
        inceptions = sorted(self.shelf.values(), reverse=True)
        return self.shelf_life - (current - inceptions[0])

    def add_request(self):
        self.check_shelf_expirations() 

        if self.request_count() >= self.limit:
            wait_time = self.wait_time() 
            print(f"Rate limited. Waiting {wait_time:.2f} seconds...")
            time.sleep(wait_time)

            self.check_shelf_expirations() 
        
        if self.request_count() >= self.limit:
            raise ValueError("Should have space on shelf, but still at capacity. Investigation needed.")

        self.shelf[str(uuid.uuid4())] = time.time() 
    
    def persist_state(self):
        os.makedirs(self.persistence_dir, exist_ok=True) 

        with open(self.persistence_dir + "/" + self.persistence_file, "w") as file:
            json.dump(self.shelf, file, indent=4)
    
    def load_persisted_state(self):
        file_path = self.persistence_dir + "/" + self.persistence_file
        if os.path.exists(file_path):
            try:
                with open(file_path, "r") as file:
                    self.shelf = json.load(file)
                    self.check_shelf_expirations() 
            except json.JSONDecodeError:
                self.shelf = {} 