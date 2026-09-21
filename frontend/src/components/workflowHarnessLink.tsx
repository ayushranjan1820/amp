import * as React from 'react';
import { LinkWidget } from '@projectstorm/react-diagrams-core';
import type { DiagramEngine } from '@projectstorm/react-diagrams-core';
import type { PointModel } from '@projectstorm/react-diagrams-core';
import {
  DefaultLinkFactory,
  DefaultLinkModel,
  DefaultLinkPointWidget,
  DefaultLinkSegmentWidget,
} from '@projectstorm/react-diagrams-defaults';
import { BezierCurve } from '@projectstorm/geometry';
import type { FlowGraphStepInput } from '../utils/workflowFlowGraph';

export class HarnessLinkModel extends DefaultLinkModel {
  edgeFrom = 0;
  edgeTo = 0;

  constructor(from?: number, to?: number) {
    super({
      type: 'harness-link',
      width: 2.2,
      color: 'rgba(139, 92, 246, 0.85)',
    });
    if (from !== undefined && to !== undefined) {
      this.edgeFrom = from;
      this.edgeTo = to;
    }
  }

  setEdge(from: number, to: number): this {
    this.edgeFrom = from;
    this.edgeTo = to;
    return this;
  }
}

function cubicBezierMid(
  p0: { x: number; y: number },
  p1: { x: number; y: number },
  p2: { x: number; y: number },
  p3: { x: number; y: number },
  t = 0.5,
): { x: number; y: number } {
  const mt = 1 - t;
  const x =
    mt ** 3 * p0.x + 3 * mt ** 2 * t * p1.x + 3 * mt * t ** 2 * p2.x + t ** 3 * p3.x;
  const y =
    mt ** 3 * p0.y + 3 * mt ** 2 * t * p1.y + 3 * mt * t ** 2 * p2.y + t ** 3 * p3.y;
  return { x, y };
}

function harnessLinkMid(link: HarnessLinkModel): { x: number; y: number } | null {
  const points = link.getPoints();
  if (points.length !== 2) return null;

  const curve = new BezierCurve();
  curve.setSource(link.getFirstPoint().getPosition());
  curve.setTarget(link.getLastPoint().getPosition());
  curve.setSourceControl(link.getFirstPoint().getPosition().clone());
  curve.setTargetControl(link.getLastPoint().getPosition().clone());

  const sp = link.getSourcePort();
  const tp = link.getTargetPort();
  if (sp) {
    curve.getSourceControl().translate(...link.calculateControlOffset(sp));
  }
  if (tp) {
    curve.getTargetControl().translate(...link.calculateControlOffset(tp));
  }

  const p0 = curve.getSource();
  const p1 = curve.getSourceControl();
  const p2 = curve.getTargetControl();
  const p3 = curve.getTarget();
  return cubicBezierMid(p0, p1, p2, p3, 0.5);
}

function harnessConfigured(steps: FlowGraphStepInput[], edgeFrom: number, edgeTo: number): boolean {
  const step = steps.find((s) => s.step_number === edgeTo);
  const cfg = step?.prompt_harness?.[String(edgeFrom)];
  return !!(cfg?.expected_output_description || '').trim();
}

interface HarnessLinkWidgetProps {
  link: HarnessLinkModel;
  diagramEngine: DiagramEngine;
  steps: FlowGraphStepInput[];
  onHarnessClick?: (fromStep: number, toStep: number) => void;
}

/** Same behavior as DefaultLinkWidget, plus a midpoint Prompt Harness control. */
export function HarnessLinkWidget({ link, diagramEngine, steps, onHarnessClick }: HarnessLinkWidgetProps) {
  const [selected, setSelected] = React.useState(false);
  const refPaths = React.useRef<Array<React.RefObject<SVGPathElement | null>>>([]);

  React.useEffect(() => {
    link.setRenderedPaths(refPaths.current.map((ref) => ref.current).filter(Boolean) as SVGPathElement[]);
    return () => {
      link.setRenderedPaths([]);
    };
  }, [link]);

  const generateRef = (): React.RefObject<SVGPathElement | null> => {
    const ref = React.createRef<SVGPathElement>();
    refPaths.current.push(ref);
    return ref;
  };

  const addPointToLink = (event: React.MouseEvent, index: number) => {
    if (
      !event.shiftKey &&
      !link.isLocked() &&
      link.getPoints().length - 1 <= diagramEngine.getMaxNumberPointsPerLink()
    ) {
      const position = diagramEngine.getRelativeMousePoint(event.nativeEvent);
      const point = link.point(position.x, position.y, index);
      event.persist();
      event.stopPropagation();
      diagramEngine.getActionEventBus().fireAction({
        event,
        model: point,
      });
    }
  };

  const generatePoint = (point: PointModel) => (
    <DefaultLinkPointWidget
      key={point.getID()}
      point={point}
      colorSelected={link.getOptions().selectedColor ?? ''}
      color={link.getOptions().color}
    />
  );

  const factory = diagramEngine.getFactoryForLink(link) as DefaultLinkFactory;

  const generateLink = (path: string, extraProps: Record<string, unknown>, id: string | number) => (
    <DefaultLinkSegmentWidget
      key={`link-${id}`}
      path={path}
      selected={selected}
      diagramEngine={diagramEngine}
      factory={factory}
      link={link}
      forwardRef={generateRef() as React.RefObject<SVGPathElement>}
      onSelection={setSelected}
      extras={extraProps}
    />
  );

  const points = link.getPoints();
  const paths: React.ReactNode[] = [];
  refPaths.current = [];

  const renderPoints = () => true;

  if (points.length === 2) {
    paths.push(
      generateLink(link.getSVGPath(), {
        onMouseDown: (event: React.MouseEvent) => {
          addPointToLink(event, 1);
        },
      }, '0'),
    );
    if (link.getTargetPort() == null) {
      paths.push(generatePoint(points[1]));
    }
  } else {
    for (let j = 0; j < points.length - 1; j++) {
      paths.push(
        generateLink(
          LinkWidget.generateLinePath(points[j], points[j + 1]),
          {
            'data-linkid': link.getID(),
            'data-point': j,
            onMouseDown: (event: React.MouseEvent) => {
              addPointToLink(event, j + 1);
            },
          },
          j,
        ),
      );
    }
    if (renderPoints()) {
      for (let i = 1; i < points.length - 1; i++) {
        paths.push(generatePoint(points[i]));
      }
      if (link.getTargetPort() == null) {
        paths.push(generatePoint(points[points.length - 1]));
      }
    }
  }

  const mid = harnessLinkMid(link);
  const active = harnessConfigured(steps, link.edgeFrom, link.edgeTo);

  return (
    <g data-harness-link="">
      <g>{paths}</g>
      {mid ? (
        <foreignObject x={mid.x - 56} y={mid.y - 18} width={112} height={36} className="overflow-visible">
          <div className="flex h-full w-full items-center justify-center">
            <button
              type="button"
              title="Prompt Harness — refine upstream output before this step"
              className={`pointer-events-auto rounded-md border px-1 py-1 font-body text-[8px] font-semibold uppercase leading-tight tracking-wide shadow-[0_4px_14px_-6px_rgba(0,0,0,0.85)] backdrop-blur-sm transition-colors ${
                active
                  ? 'border-cyan-400/50 bg-cyan-950/90 text-cyan-100 hover:border-cyan-300/70'
                  : 'border-white/20 bg-[#0d0828]/90 text-zinc-200 hover:border-violet-400/45 hover:text-gray-900 dark:hover:text-white'
              }`}
              onMouseDown={(e) => {
                e.preventDefault();
                e.stopPropagation();
              }}
              onClick={(e) => {
                e.preventDefault();
                e.stopPropagation();
                onHarnessClick?.(link.edgeFrom, link.edgeTo);
              }}
            >
              Prompt
              <br />
              Harness
            </button>
          </div>
        </foreignObject>
      ) : null}
    </g>
  );
}

export class HarnessLinkFactory extends DefaultLinkFactory {
  private readonly opts: () => {
    steps: FlowGraphStepInput[];
    onHarnessClick?: (fromStep: number, toStep: number) => void;
  };

  constructor(opts: HarnessLinkFactory['opts']) {
    super('harness-link');
    this.opts = opts;
  }

  generateReactWidget(event: { model: HarnessLinkModel }) {
    const { steps, onHarnessClick } = this.opts();
    return (
      <HarnessLinkWidget
        link={event.model}
        diagramEngine={this.engine}
        steps={steps}
        onHarnessClick={onHarnessClick}
      />
    );
  }

  generateModel() {
    return new HarnessLinkModel();
  }
}
