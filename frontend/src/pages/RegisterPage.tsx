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
        />

        <Form.Group className="mb-4" controlId="register-terms">
          <Form.Check
            type="checkbox"
            name="agreeTerms"
            label="I agree to the Terms of Service & Privacy Policy"
            checked={formData.agreeTerms}
            onChange={handleChange}
            className="text-secondary small form-check-input-custom"
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
