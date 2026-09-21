declare module 'react-simple-maps' {
  type ReactNode = import('react').ReactNode;
  type ComponentType<P = Record<string, unknown>> = import('react').ComponentType<P>;

  export interface RsmGeography {
    rsmKey: string;
    properties: Record<string, unknown>;
    type?: string;
    geometry?: unknown;
  }

  export const ComposableMap: ComponentType<Record<string, unknown>>;

  export const Geographies: ComponentType<{
    geography: string;
    children: (arg: { geographies: RsmGeography[] }) => ReactNode;
  }>;

  export const Geography: ComponentType<Record<string, unknown>>;

  export const Marker: ComponentType<{
    coordinates: [number, number];
    children?: ReactNode;
  }>;
}
