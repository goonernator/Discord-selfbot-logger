# Testing Guide

## Quick Test

Run the comprehensive import test:
```bash
python test_imports.py
```

## Running Unit Tests

### Using pytest (recommended):
```bash
python -m pytest tests/ -v
```

### Using unittest (built-in):
```bash
python -m unittest discover tests -v
```

## Individual Module Tests

Test specific modules:
```bash
# Test security module
python -m unittest tests.test_security -v

# Test config module  
python -m unittest tests.test_config -v
```

## Manual Import Testing

Test if modules can be imported:
```bash
python -c "from security import TokenValidator; print('OK')"
python -c "from database import get_database; print('OK')"
python -c "from monitoring import get_monitoring_system; print('OK')"
```

## Common Issues

### "No module named X"
1. Make sure you're using the same Python interpreter:
   ```bash
   python --version
   python -m pip --version
   ```

2. Install requirements:
   ```bash
   python -m pip install -r requirements.txt
   ```

3. If using a virtual environment, activate it first:
   ```bash
   # Windows
   venv\Scripts\activate
   
   # Linux/Mac
   source venv/bin/activate
   ```

### Import Errors
- Make sure you're running from the project root directory
- Check that `sys.path` includes the current directory
- Verify all dependencies are installed: `python -m pip list`

## Test Coverage

Current test coverage:
- ✓ Security module (TokenValidator, InputSanitizer)
- ✓ Config module (basic functionality)
- ✓ All module imports
- ✓ Basic functionality tests

## Adding New Tests

1. Create test file in `tests/` directory
2. Follow naming convention: `test_<module_name>.py`
3. Use unittest or pytest framework
4. Run tests before committing changes

