from rate_limiting import RateLimiter
import time 

def test_add_request():
    limiter = RateLimiter(persist=False)
    limiter.add_request()

    assert limiter.request_count() == 1

def test_request_shelf_life():
    limiter = RateLimiter(persist=False, shelf_life=2)
    limiter.add_request() 

    assert limiter.request_count() == 1

    time.sleep(2)

    assert limiter.request_count() == 0

def test_request_limit(capsys):
    limiter = RateLimiter(persist=False, limit=2, shelf_life=2)

    for i in range(2):
        limiter.add_request() 

        assert limiter.request_count() == i + 1

    limiter.add_request() 
    captured = capsys.readouterr()

    assert "Rate limited" in captured.out.strip() 

def test_persistence(tmp_path):
    limiter = RateLimiter(persistence_dir=str(tmp_path), persistence_file="state.json")

    limiter.add_request()
    limiter.persist_state() 

    restored = RateLimiter(persistence_dir=str(tmp_path), persistence_file="state.json")

    assert restored.request_count() == 1

def test_full_function(capsys):
    limiter = RateLimiter(persist=False, limit=2, shelf_life=2)

    for i in range(2):
        limiter.add_request() 

        assert limiter.request_count() == i + 1 
    
    limiter.add_request() 
    captured = capsys.readouterr() 

    assert "Rate limited" in captured.out.strip()

    time.sleep(2)
    
    assert limiter.request_count() == 0

    