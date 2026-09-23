import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Form, Button, Alert, Spinner } from 'react-bootstrap';
import { AuthLayout } from '../components/auth/AuthLayout';
import { InputField } from '../components/common/InputField';
import { post, extractErrorMessage } from '../services/apiWrapper';
import { API_ENDPOINTS } from '../constants';

export const RegisterPage: React.FC = () => {
  const navigate = useNavigate();

  const [formData, setFormData] = useState({
    name: '',
    email: '',
    password: '',
    confirmPassword: '',
    agreeTerms: false,
  });

  const [errors, setErrors] = useState<{
    name?: string;
    email?: string;
    password?: string;
    confirmPassword?: string;
    agreeTerms?: string;
  }>({});

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
    const newErrors: typeof errors = {};

    if (!formData.name.trim()) {
      newErrors.name = 'Full name is required';
    }

    if (!formData.email.trim()) {
      newErrors.email = 'Email address is required';
    } else if (!/\S+@\S+\.\S+/.test(formData.email)) {
      newErrors.email = 'Please enter a valid email address';
    }

    if (!formData.password) {
      newErrors.password = 'Password is required';
    } else if (formData.password.length < 6) {
      newErrors.password = 'Password must be at least 6 characters long';
    }

    if (formData.password !== formData.confirmPassword) {
      newErrors.confirmPassword = 'Passwords do not match';
    }

    if (!formData.agreeTerms) {
      newErrors.agreeTerms = 'You must agree to the Terms of Service';
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
        name: formData.name,
        email: formData.email,
        password: formData.password,
        confirm_password: formData.confirmPassword,
      };

      await post(API_ENDPOINTS.AUTH.REGISTER, payload);

      // On successful registration, navigate to login page
      navigate('/login');
    } catch (err) {
      const message = extractErrorMessage(err);
      setServerError(message);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <AuthLayout title="Create Your Account" subtitle="Join AgentMart to deploy & manage AI agents">
      {serverError && (
        <Alert variant="danger" className="alert-custom-error mb-4">
          {serverError}
        </Alert>
      )}

      <Form onSubmit={handleSubmit} noValidate>
        <InputField
          id="register-name"
          label="Full Name"
          type="text"
          name="name"
          value={formData.name}
          placeholder="John Doe"
          onChange={handleChange}
          error={errors.name}
          required
          autoComplete="name"
          icon={
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="currentColor" viewBox="0 0 16 16">
              <path d="M8 8a3 3 0 1 0 0-6 3 3 0 0 0 0 6m2-3a2 2 0 1 1-4 0 2 2 0 0 1 4 0m4 8c0 1-1 1-1 1H3s-1 0-1-1 1-4 6-4 6 3 6 4m-1-.004c-.001-.246-.154-.986-.832-1.664C11.516 10.68 10.289 10 8 10s-3.516.68-4.168 1.332c-.678.678-.83 1.418-.832 1.664z"/>
            </svg>
          }
        />

        <InputField
          id="register-email"
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
          id="register-password"
          label="Password"
          type="password"
          name="password"
          value={formData.password}
          placeholder="••••••••"
          onChange={handleChange}
          error={errors.password}
          required
          showPasswordToggle
          autoComplete="new-password"
          icon={
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="currentColor" viewBox="0 0 16 16">
              <path d="M8 1a2 2 0 0 1 2 2v4H6V3a2 2 0 0 1 2-2m3 6V3a3 3 0 0 0-6 0v4a2 2 0 0 0-2 2v5a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2M5 9a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v5a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1z"/>
            </svg>
          }
        />

        <InputField
          id="register-confirm-password"
          label="Confirm Password"
          type="password"
          name="confirmPassword"
          value={formData.confirmPassword}
          placeholder="••••••••"
          onChange={handleChange}
          error={errors.confirmPassword}
          required
          showPasswordToggle
          autoComplete="new-password"
          icon={
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="currentColor" viewBox="0 0 16 16">
              <path d="M10.854 7.146a.5.5 0 0 1 0 .708l-3 3a.5.5 0 0 1-.708 0l-1.5-1.5a.5.5 0 1 1 .708-.708L7.5 9.793l2.646-2.647a.5.5 0 0 1 .708 0"/>
              <path d="M8 1a2 2 0 0 1 2 2v4H6V3a2 2 0 0 1 2-2m3 6V3a3 3 0 0 0-6 0v4a2 2 0 0 0-2 2v5a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2"/>
            </svg>
          }
        />

        <Form.Group className="mb-4" controlId="register-terms">
          <Form.Check
            type="checkbox"
            name="agreeTerms"
            checked={formData.agreeTerms}
            onChange={handleChange}
            className="text-secondary small form-check-input-custom"
            label={
              <span>
                I agree to the{' '}
                <a href="#terms" className="link-cyan" onClick={(e) => e.preventDefault()}>
                  Terms of Service
                </a>{' '}
                and{' '}
                <a href="#privacy" className="link-cyan" onClick={(e) => e.preventDefault()}>
                  Privacy Policy
                </a>
              </span>
            }
          />
          {errors.agreeTerms && <div className="text-danger mt-1 small">{errors.agreeTerms}</div>}
        </Form.Group>

        <Button
          type="submit"
          className="btn-cyan-primary w-100 mb-3 d-flex align-items-center justify-content-center gap-2"
          disabled={isLoading}
        >
          {isLoading ? (
            <>
              <Spinner animation="border" size="sm" />
              <span>Creating Account...</span>
            </>
          ) : (
            'Create Account'
          )}
        </Button>
      </Form>

      <div className="text-center mt-3 text-secondary small">
        Already have an account?{' '}
        <Link to="/login" className="link-cyan fw-semibold">
          Sign In
        </Link>
      </div>
    </AuthLayout>
  );
};
