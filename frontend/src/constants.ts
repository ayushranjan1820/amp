// Base API Configuration
export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '';

// API Endpoints Registry
export const API_ENDPOINTS = {
  AUTH: {
    LOGIN: '/api/v1/users/login',
    REGISTER: '/api/v1/users/register',
  },
} as const;
