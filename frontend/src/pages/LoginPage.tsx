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

      const userData = (response && 'data' in response && response.data)
        ? response.data
        : (response as UserSession);

      loginUser({
        name: userData.name,
        email: userData.email,
        token: userData.token,
      });

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
        />

        <div className="mb-4">
          <Form.Check
            type="checkbox"
            id="remember-me"
            name="rememberMe"
            label="Remember me"
            checked={formData.rememberMe}
            onChange={handleChange}
            className="text-secondary small form-check-input-custom"
          />
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
