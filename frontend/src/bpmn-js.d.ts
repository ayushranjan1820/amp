declare module 'bpmn-js' {
  interface BpmnJSOptions {
    container?: HTMLElement | string;
    width?: string | number;
    height?: string | number;
    moddleExtensions?: object;
    additionalModules?: any[];
  }

  interface Canvas {
    zoom(level: number | 'fit-viewport'): number;
  }

  interface ImportResult {
    warnings: string[];
  }

  interface SaveSVGResult {
    svg: string;
  }

  interface SaveXMLResult {
    xml: string;
  }

  class BpmnJS {
    constructor(options?: BpmnJSOptions);
    importXML(xml: string): Promise<ImportResult>;
    saveSVG(): Promise<SaveSVGResult>;
    saveXML(options?: { format?: boolean }): Promise<SaveXMLResult>;
    get(name: 'canvas'): Canvas;
    get(name: string): any;
    destroy(): void;
    on(event: string, callback: Function): void;
    off(event: string, callback: Function): void;
  }

  export default BpmnJS;
}

declare module 'bpmn-js/lib/Modeler' {
  interface BpmnModelerOptions {
    container?: HTMLElement | string;
    width?: string | number;
    height?: string | number;
    moddleExtensions?: object;
    additionalModules?: any[];
    keyboard?: { bindTo?: Document | HTMLElement };
  }

  interface Canvas {
    zoom(level: number | 'fit-viewport'): number;
  }

  class BpmnModeler {
    constructor(options?: BpmnModelerOptions);
    importXML(xml: string): Promise<{ warnings: string[] }>;
    saveXML(options?: { format?: boolean }): Promise<{ xml: string }>;
    saveSVG(): Promise<{ svg: string }>;
    get(name: 'canvas'): Canvas;
    get(name: string): any;
    on(event: string, callback: (...args: any[]) => void): void;
    off(event: string, callback?: (...args: any[]) => void): void;
    destroy(): void;
  }

  export default BpmnModeler;
}
