import React, { useState } from 'react';
import { Form, InputGroup } from 'react-bootstrap';
import './InputField.css';

interface InputFieldProps {
  id: string;
  label: string;
  type: string;
  name: string;
  value: string;
  placeholder?: string;
  onChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
  error?: string;
  required?: boolean;
  autoComplete?: string;
  showPasswordToggle?: boolean;
}

export const InputField: React.FC<InputFieldProps> = ({
  id,
  label,
  type,
  name,
  value,
  placeholder,
  onChange,
  error,
  required = false,
  autoComplete,
  showPasswordToggle = false,
}) => {
  const [showPassword, setShowPassword] = useState(false);

  const inputType = showPasswordToggle ? (showPassword ? 'text' : 'password') : type;

  return (
    <Form.Group className="mb-3" controlId={id}>
      {label && <Form.Label className="form-label-custom">{label}</Form.Label>}
      <InputGroup>
        <Form.Control
          type={inputType}
          name={name}
          value={value}
          placeholder={placeholder}
          onChange={onChange}
          required={required}
          autoComplete={autoComplete}
          className={`custom-input ${error ? 'is-invalid' : ''}`}
        />
        {showPasswordToggle && (
          <InputGroup.Text
            className="input-group-text-custom small fw-medium user-select-none"
            onClick={() => setShowPassword(!showPassword)}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                setShowPassword(!showPassword);
              }
            }}
          >
            {showPassword ? 'Hide' : 'Show'}
          </InputGroup.Text>
        )}
      </InputGroup>
      {error && <div className="text-danger mt-1 small">{error}</div>}
    </Form.Group>
  );
};
