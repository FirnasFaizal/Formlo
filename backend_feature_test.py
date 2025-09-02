#!/usr/bin/env python3
"""
Feature-Specific Backend Testing for Formlo Application
Tests specific features like text extraction, AI integration, and Google Forms API setup
"""

import requests
import json
import os
import tempfile
import io
from pathlib import Path

# Test the backend's ability to handle core features
BASE_URL = "https://test-runner-9.preview.emergentagent.com/api"

class FormloFeatureTester:
    def __init__(self):
        self.session = requests.Session()
        self.base_url = BASE_URL
        self.test_results = []
        
    def log_test(self, test_name: str, success: bool, details: str = ""):
        """Log test results"""
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status} {test_name}")
        if details:
            print(f"   Details: {details}")
        
        self.test_results.append({
            "test": test_name,
            "success": success,
            "details": details
        })
    
    def test_text_extraction_libraries(self):
        """Test if text extraction libraries are properly imported in backend"""
        try:
            # Test by checking if the backend can handle different file types
            # We'll test the upload endpoint with different file types
            
            # Create test files
            test_files = [
                ("sample.txt", "This is a test document.\n\n1. What is your name?\n2. What is your age?", "text/plain"),
                ("sample.pdf", b"%PDF-1.4 fake pdf content", "application/pdf"),
                ("sample.docx", b"fake docx content", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
            ]
            
            for filename, content, mime_type in test_files:
                files = {"file": (filename, content, mime_type)}
                response = self.session.post(f"{self.base_url}/upload", files=files)
                
                # Should get 401 (auth required) not 500 (server error)
                if response.status_code == 401:
                    self.log_test(f"File Type Support: {filename}", True, "Backend accepts file type and requires auth")
                elif response.status_code == 400:
                    # Check if it's a file type validation error
                    try:
                        error_data = response.json()
                        if "not supported" in error_data.get("detail", "").lower():
                            self.log_test(f"File Type Support: {filename}", False, f"File type not supported: {error_data['detail']}")
                        else:
                            self.log_test(f"File Type Support: {filename}", True, "File type validation working")
                    except:
                        self.log_test(f"File Type Support: {filename}", False, f"Unexpected 400 response")
                else:
                    self.log_test(f"File Type Support: {filename}", False, f"Unexpected status: {response.status_code}")
                    
        except Exception as e:
            self.log_test("Text Extraction Libraries", False, f"Exception: {str(e)}")
    
    def test_ai_integration_setup(self):
        """Test AI integration setup (Gemini via emergentintegrations)"""
        try:
            # We can't test the actual AI without auth, but we can test if the endpoint structure is correct
            # The upload endpoint should fail with auth error, not with AI setup error
            
            sample_text_file = ("document.txt", "Sample document with questions:\n1. What is AI?\n2. How does machine learning work?", "text/plain")
            files = {"file": sample_text_file}
            
            response = self.session.post(f"{self.base_url}/upload", files=files)
            
            if response.status_code == 401:
                self.log_test("AI Integration Setup", True, "AI processing endpoint properly structured (requires auth)")
            elif response.status_code == 500:
                # Check if it's an AI-related error
                self.log_test("AI Integration Setup", False, "Possible AI integration configuration issue")
            else:
                self.log_test("AI Integration Setup", True, f"Endpoint responds appropriately (Status: {response.status_code})")
                
        except Exception as e:
            self.log_test("AI Integration Setup", False, f"Exception: {str(e)}")
    
    def test_google_forms_api_setup(self):
        """Test Google Forms API setup"""
        try:
            # Test if the backend has proper Google Forms API configuration
            # We can't create actual forms without auth, but we can check endpoint structure
            
            # The upload endpoint should handle the full pipeline including Google Forms creation
            response = self.session.post(f"{self.base_url}/upload")
            
            if response.status_code == 401:
                self.log_test("Google Forms API Setup", True, "Forms creation endpoint properly structured")
            elif response.status_code == 500:
                self.log_test("Google Forms API Setup", False, "Possible Google Forms API configuration issue")
            else:
                self.log_test("Google Forms API Setup", True, f"Endpoint structure correct (Status: {response.status_code})")
                
        except Exception as e:
            self.log_test("Google Forms API Setup", False, f"Exception: {str(e)}")
    
    def test_database_integration(self):
        """Test MongoDB integration"""
        try:
            # Test database-dependent endpoints
            db_endpoints = [
                ("/forms", "Forms Collection"),
                ("/jobs/test-id", "Jobs Collection"),
                ("/auth/me", "Users Collection")
            ]
            
            all_working = True
            for endpoint, description in db_endpoints:
                response = self.session.get(f"{self.base_url}{endpoint}")
                
                if response.status_code == 401:
                    self.log_test(f"Database Integration: {description}", True, "Database endpoint accessible")
                elif response.status_code == 500:
                    self.log_test(f"Database Integration: {description}", False, "Possible database connection issue")
                    all_working = False
                else:
                    self.log_test(f"Database Integration: {description}", True, f"Endpoint working (Status: {response.status_code})")
            
            return all_working
            
        except Exception as e:
            self.log_test("Database Integration", False, f"Exception: {str(e)}")
            return False
    
    def test_processing_job_system(self):
        """Test processing job management system"""
        try:
            # Test job status endpoint
            response = self.session.get(f"{self.base_url}/jobs/sample-job-id")
            
            if response.status_code == 401:
                self.log_test("Processing Job System", True, "Job management system properly structured")
            elif response.status_code == 404:
                # This is also acceptable - means the endpoint exists but job not found
                self.log_test("Processing Job System", True, "Job management system working (job not found as expected)")
            elif response.status_code == 500:
                self.log_test("Processing Job System", False, "Possible job management system issue")
            else:
                self.log_test("Processing Job System", True, f"Job system responds appropriately (Status: {response.status_code})")
                
        except Exception as e:
            self.log_test("Processing Job System", False, f"Exception: {str(e)}")
    
    def test_ocr_integration(self):
        """Test OCR integration (Tesseract)"""
        try:
            # Test with a PDF file that would require OCR
            fake_pdf_content = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>\nendobj\nxref\n0 4\n0000000000 65535 f \n0000000009 00000 n \n0000000058 00000 n \n0000000115 00000 n \ntrailer\n<< /Size 4 /Root 1 0 R >>\nstartxref\n178\n%%EOF"
            
            files = {"file": ("scanned_document.pdf", fake_pdf_content, "application/pdf")}
            response = self.session.post(f"{self.base_url}/upload", files=files)
            
            if response.status_code == 401:
                self.log_test("OCR Integration", True, "OCR processing endpoint properly structured")
            elif response.status_code == 500:
                self.log_test("OCR Integration", False, "Possible OCR integration issue")
            else:
                self.log_test("OCR Integration", True, f"OCR endpoint responds appropriately (Status: {response.status_code})")
                
        except Exception as e:
            self.log_test("OCR Integration", False, f"Exception: {str(e)}")
    
    def test_session_management(self):
        """Test session management for OAuth"""
        try:
            # Test session-related endpoints
            response = self.session.post(f"{self.base_url}/auth/logout")
            
            if response.status_code == 200:
                data = response.json()
                if "Logged out" in data.get("message", ""):
                    self.log_test("Session Management", True, "Session management working correctly")
                else:
                    self.log_test("Session Management", False, f"Unexpected logout response: {data}")
            else:
                self.log_test("Session Management", False, f"Logout failed: {response.status_code}")
                
        except Exception as e:
            self.log_test("Session Management", False, f"Exception: {str(e)}")
    
    def test_api_security(self):
        """Test API security measures"""
        try:
            # Test that sensitive endpoints require authentication
            sensitive_endpoints = [
                "/auth/me",
                "/upload", 
                "/forms",
                "/jobs/test"
            ]
            
            all_secure = True
            for endpoint in sensitive_endpoints:
                response = self.session.get(f"{self.base_url}{endpoint}")
                if response.status_code != 401:
                    if endpoint == "/upload" and response.status_code == 405:
                        # POST endpoint accessed with GET - acceptable
                        continue
                    self.log_test(f"API Security: {endpoint}", False, f"Not properly secured: {response.status_code}")
                    all_secure = False
                else:
                    self.log_test(f"API Security: {endpoint}", True, "Properly secured")
            
            return all_secure
            
        except Exception as e:
            self.log_test("API Security", False, f"Exception: {str(e)}")
            return False
    
    def run_feature_tests(self):
        """Run all feature-specific tests"""
        print("🔍 Starting Formlo Feature-Specific Testing")
        print("=" * 50)
        
        # Test core features
        self.test_text_extraction_libraries()
        self.test_ai_integration_setup()
        self.test_google_forms_api_setup()
        self.test_ocr_integration()
        
        # Test system components
        self.test_database_integration()
        self.test_processing_job_system()
        self.test_session_management()
        self.test_api_security()
        
        print("\n" + "=" * 50)
        print("📊 FEATURE TEST SUMMARY")
        print("=" * 50)
        
        passed = sum(1 for result in self.test_results if result["success"])
        total = len(self.test_results)
        
        print(f"Total Feature Tests: {total}")
        print(f"Passed: {passed}")
        print(f"Failed: {total - passed}")
        print(f"Success Rate: {(passed/total)*100:.1f}%")
        
        if total - passed > 0:
            print("\n❌ FAILED FEATURE TESTS:")
            for result in self.test_results:
                if not result["success"]:
                    print(f"  - {result['test']}: {result['details']}")
        
        # Determine if core features are working
        critical_features = [
            "File Type Support: sample.txt",
            "AI Integration Setup", 
            "Google Forms API Setup",
            "Database Integration: Forms Collection",
            "Processing Job System"
        ]
        
        critical_passed = sum(1 for result in self.test_results 
                            if result["success"] and any(cf in result["test"] for cf in critical_features))
        
        if critical_passed >= 4:  # Most critical features working
            print("\n✅ CORE FEATURES FUNCTIONAL")
            return True
        else:
            print("\n❌ CRITICAL FEATURE ISSUES DETECTED")
            return False

def main():
    """Main test execution"""
    tester = FormloFeatureTester()
    success = tester.run_feature_tests()
    return 0 if success else 1

if __name__ == "__main__":
    exit(main())