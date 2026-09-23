import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Form, Button, Alert, Spinner } from 'react-bootstrap';
import { AuthLayout } from '../components/auth/AuthLayout';
import { InputField } from '../components/common/InputField';
import { post, extractErrorMessage, type ApiResponse } from '../services/apiWrapper';
import { API_ENDPOINTS } from '../constants';
import { useAuth, type UserSession } from '../context/AuthContext';

export const LoginPage: React.FC = () => {
  const navigate = useNavigate();
  const { loginUser } = useAuth();

  const [formData, setFormData] = useState({
    email: '',
    password: '',
    rememberMe: false,
  });

  const [errors, setErrors] = useState<{ email?: string; password?: string }>({});
  const [serverError, setServerError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const { name, value, type, checked } = e.target;
    setFormData((prev) => ({
      ...prev,
      [name]: type === 'checkbox' ? checked : value,
    }));

    if (errors[name as keyof typeof errors]) {
      setErrors((prev) => ({ ...prev, [name]: undefined }));
    }
    if (serverError) setServerError(null);
  };

  const validate = () => {
    const newErrors: { email?: string; password?: string } = {};
    if (!formData.email.trim()) {
      newErrors.email = 'Email address is required';
    } else if (!/\S+@\S+\.\S+/.test(formData.email)) {
      newErrors.email = 'Please enter a valid email address';
    }

    if (!formData.password) {
      newErrors.password = 'Password is required';
    }

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!validate()) return;

    setIsLoading(true);
    setServerError(null);

    try {
      const payload = {
        email: formData.email,
        password: formData.password,
      };

      const response = await post<ApiResponse<UserSession> | UserSession>(API_ENDPOINTS.AUTH.LOGIN, payload);

      // Extract user data from response envelope { data: { name, email, token } } or direct object
      const userData = (response && 'data' in response && response.data)
        ? response.data
        : (response as UserSession);

      // Save user session (name, email, token) in AuthContext & sessionStorage
      loginUser({
        name: userData.name,
        email: userData.email,
        token: userData.token,
      });

      // Navigate to landing page
      navigate('/');
    } catch (err) {
      const message = extractErrorMessage(err);
      setServerError(message);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <AuthLayout title="Sign In to Your Account" subtitle="Access intelligent AI agents & marketplace">
      {serverError && (
        <Alert variant="danger" className="alert-custom-error mb-4">
          {serverError}
        </Alert>
      )}

      <Form onSubmit={handleSubmit} noValidate>
        <InputField
          id="login-email"
          label="Email Address"
          type="email"
          name="email"
          value={formData.email}
          placeholder="name@example.com"
          onChange={handleChange}
          error={errors.email}
          required
          autoComplete="email"
          icon={
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="currentColor" viewBox="0 0 16 16">
              <path d="M0 4a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H2a2 2 0 0 1-2-2zm2-1a1 1 0 0 0-1 1v.217l7 4.2 7-4.2V4a1 1 0 0 0-1-1zm13 2.383-4.708 2.825L15 11.105zm-.034 6.876-5.64-3.471L8 9.583l-1.326-.795-5.64 3.47A1 1 0 0 0 2 13h12a1 1 0 0 0 .966-.741M1 11.105l4.708-2.897L1 5.383z"/>
            </svg>
          }
        />

        <InputField
          id="login-password"
          label="Password"
          type="password"
          name="password"
          value={formData.password}
          placeholder="••••••••"
          onChange={handleChange}
          error={errors.password}
          required
          showPasswordToggle
          autoComplete="current-password"
          icon={
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="currentColor" viewBox="0 0 16 16">
              <path d="M8 1a2 2 0 0 1 2 2v4H6V3a2 2 0 0 1 2-2m3 6V3a3 3 0 0 0-6 0v4a2 2 0 0 0-2 2v5a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2M5 9a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v5a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1z"/>
            </svg>
          }
        />

        <div className="d-flex justify-content-between align-items-center mb-4">
          <Form.Check
            type="checkbox"
            id="remember-me"
            name="rememberMe"
            label="Remember me"
            checked={formData.rememberMe}
            onChange={handleChange}
            className="text-secondary small form-check-input-custom"
          />
          <a href="#forgot-password" className="link-cyan small" onClick={(e) => e.preventDefault()}>
            Forgot password?
          </a>
        </div>

        <Button
          type="submit"
          className="btn-cyan-primary w-100 mb-3 d-flex align-items-center justify-content-center gap-2"
          disabled={isLoading}
        >
          {isLoading ? (
            <>
              <Spinner animation="border" size="sm" />
              <span>Signing in...</span>
            </>
          ) : (
            'Sign In'
          )}
        </Button>
      </Form>

      <div className="text-center mt-3 text-secondary small">
        Don't have an account?{' '}
        <Link to="/register" className="link-cyan fw-semibold">
          Create account
        </Link>
      </div>
    </AuthLayout>
  );
};
