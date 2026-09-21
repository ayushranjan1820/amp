"""
Test script for BRD Generation Agent
Run this to verify your installation and configuration.
"""

import os
import sys
from pathlib import Path

def test_imports():
    """Test if all required modules can be imported."""
    print("🔍 Testing imports...")
    try:
        import langchain
        print("  ✓ langchain")
        import langchain_core
        print("  ✓ langchain_core")
        import requests
        print("  ✓ requests")
        import dotenv
        print("  ✓ python-dotenv")
        from ddgs import DDGS
        print("  ✓ ddgs")
        import pydantic
        print("  ✓ pydantic")
        print("✅ All imports successful!\n")
        return True
    except ImportError as e:
        print(f"❌ Import error: {e}")
        print("💡 Run: pip install -r requirements.txt\n")
        return False

def test_env_file():
    """Test if .env file exists and has required variables."""
    print("🔍 Testing environment configuration...")
    env_path = Path(__file__).parent / '.env'
    
    if not env_path.exists():
        print("  ❌ .env file not found")
        print("  💡 Copy .env.example to .env and add your credentials\n")
        return False
    
    print("  ✓ .env file exists")
    
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=env_path)
    
    api_key = os.getenv("PWC_GENAI_API_KEY") or os.getenv("GEMINI_API_KEY")
    
    if not api_key:
        print("  ❌ PWC_GENAI_API_KEY not configured")
        print("  💡 Add your API key to the .env file\n")
        return False
    
    print(f"  ✓ API key configured (length: {len(api_key)} chars)")
    print("✅ Environment configuration looks good!\n")
    return True

def test_directories():
    """Test if required directories exist."""
    print("🔍 Testing directory structure...")
    
    base_dir = Path(__file__).parent
    required_dirs = [
        base_dir / "tools",
        base_dir / "outputs"
    ]
    
    all_exist = True
    for dir_path in required_dirs:
        if dir_path.exists():
            print(f"  ✓ {dir_path.name}/ exists")
        else:
            print(f"  ❌ {dir_path.name}/ not found")
            all_exist = False
    
    if all_exist:
        print("✅ Directory structure is correct!\n")
    else:
        print("❌ Some directories are missing\n")
    
    return all_exist

def test_tools():
    """Test if tools can be imported."""
    print("🔍 Testing tools...")
    try:
        from tools import generate_brd, tools_list
        print(f"  ✓ generate_brd tool")
        print(f"  ✓ tools_list ({len(tools_list)} tools)")
        print("✅ All tools loaded successfully!\n")
        return True
    except Exception as e:
        print(f"  ❌ Error loading tools: {e}\n")
        return False

def test_agent():
    """Test if the agent can be initialized."""
    print("🔍 Testing agent initialization...")
    try:
        from agent import BRDGenerationAgent
        agent = BRDGenerationAgent()
        print("  ✓ Agent initialized successfully")
        print(f"  ✓ Agent has {len(agent.tools)} tools available")
        print("✅ Agent is ready to use!\n")
        return True
    except Exception as e:
        print(f"  ❌ Error initializing agent: {e}\n")
        return False

def main():
    """Run all tests."""
    print("=" * 60)
    print("🧪 BRD Generation Agent - Installation Test")
    print("=" * 60)
    print()
    
    results = []
    
    # Run tests
    results.append(("Imports", test_imports()))
    results.append(("Environment", test_env_file()))
    results.append(("Directories", test_directories()))
    results.append(("Tools", test_tools()))
    results.append(("Agent", test_agent()))
    
    # Summary
    print("=" * 60)
    print("📊 Test Summary")
    print("=" * 60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} - {test_name}")
    
    print()
    print(f"Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 All tests passed! Your BRD Generation Agent is ready to use.")
        print("\n🚀 Quick Start:")
        print("   1. Run: python agent.py")
        print("   2. Enter your project description")
        print("   3. Get your BRD in the outputs/ directory")
        print("\n📚 For detailed usage, see README.md or QUICKSTART.md")
    else:
        print("\n⚠️ Some tests failed. Please fix the issues above.")
        print("💡 Check the documentation:")
        print("   - QUICKSTART.md for setup instructions")
        print("   - README.md for detailed documentation")
    
    print()
    return passed == total

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
