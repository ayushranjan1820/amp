import {
  Document,
  HeadingLevel,
  Packer,
  Paragraph,
  Table,
  TableCell,
  TableRow,
  TextRun,
  WidthType,
} from 'docx';
import { jsPDF } from 'jspdf';

import { sanitizeExportBasename, triggerDownload } from './chatMessageExport';

function blueprintBasename(): string {
  const stamp = new Date().toISOString().slice(0, 19).replace(/[T:]/g, '-');
  return sanitizeExportBasename(`Company-AI-Blueprint-${stamp}`);
}

async function loadParsed(content: string) {
  const { parseReport } = await import('../components/CompanyAiSolutionsView');
  return parseReport(content);
}

function buildDocxSectionChildren(parsed: Awaited<ReturnType<typeof loadParsed>>): (Paragraph | Table)[] {
  const out: (Paragraph | Table)[] = [];

  out.push(
    new Paragraph({
      text: 'Company AI Solutions Blueprint',
      heading: HeadingLevel.TITLE,
    }),
  );
  out.push(
    new Paragraph({
      children: [
        new TextRun({
          text: 'Strategic assessment — opportunity areas, solution design, delivery phases, and risk posture. Generated for planning and discussion.',
          italics: true,
        }),
      ],
    }),
  );
  out.push(new Paragraph({ text: '' }));

  if (parsed.executiveSummary.length) {
    out.push(new Paragraph({ text: 'Executive summary', heading: HeadingLevel.HEADING_1 }));
    for (const item of parsed.executiveSummary) {
      out.push(
        new Paragraph({
          children: [new TextRun({ text: `• ${item}` })],
        }),
      );
    }
    out.push(new Paragraph({ text: '' }));
  }

  out.push(new Paragraph({ text: 'Context & pressure points', heading: HeadingLevel.HEADING_1 }));
  out.push(new Paragraph({ text: 'Key problems', heading: HeadingLevel.HEADING_2 }));
  if (parsed.keyProblems.length) {
    for (const item of parsed.keyProblems) {
      out.push(new Paragraph({ children: [new TextRun({ text: `• ${item}` })] }));
    }
  } else {
    out.push(
      new Paragraph({
        children: [new TextRun({ text: 'No problems extracted from the response.', italics: true })],
      }),
    );
  }
  out.push(new Paragraph({ text: 'Process improvement areas', heading: HeadingLevel.HEADING_2 }));
  if (parsed.processAreas.length) {
    for (const item of parsed.processAreas) {
      out.push(new Paragraph({ children: [new TextRun({ text: `• ${item}` })] }));
    }
  } else {
    out.push(
      new Paragraph({
        children: [
          new TextRun({ text: 'No process improvements extracted from the response.', italics: true }),
        ],
      }),
    );
  }
  out.push(new Paragraph({ text: '' }));

  out.push(new Paragraph({ text: 'Recommended solutions', heading: HeadingLevel.HEADING_1 }));
  if (parsed.solutions.length === 0) {
    out.push(
      new Paragraph({
        children: [new TextRun({ text: 'No structured solution cards found in output.', italics: true })],
      }),
    );
  } else {
    for (let i = 0; i < parsed.solutions.length; i++) {
      const s = parsed.solutions[i]!;
      out.push(
        new Paragraph({
          text: `${i + 1}. ${s.name}`,
          heading: HeadingLevel.HEADING_2,
        }),
      );
      if (s.type) {
        out.push(new Paragraph({ children: [new TextRun({ text: `Type: ${s.type}` })] }));
      }
      if (s.source) {
        out.push(new Paragraph({ children: [new TextRun({ text: `Source: ${s.source}` })] }));
      }
      out.push(
        new Paragraph({
          children: [new TextRun({ text: `Relevance: ${s.why || 'Not provided'}` })],
        }),
      );
      out.push(
        new Paragraph({
          children: [new TextRun({ text: `Implementation plan: ${s.plan || 'Not provided'}` })],
        }),
      );
      out.push(
        new Paragraph({
          children: [new TextRun({ text: `Dependencies: ${s.dependencies || 'Not provided'}` })],
        }),
      );
      out.push(
        new Paragraph({
          children: [new TextRun({ text: `Expected business impact: ${s.impact || 'Not provided'}` })],
        }),
      );
      out.push(
        new Paragraph({
          children: [new TextRun({ text: `Delivery horizon: ${s.horizon || 'Not provided'}` })],
        }),
      );
      out.push(new Paragraph({ text: '' }));
    }
  }

  out.push(new Paragraph({ text: 'Implementation roadmap', heading: HeadingLevel.HEADING_1 }));
  if (parsed.roadmap.length === 0) {
    out.push(
      new Paragraph({
        children: [new TextRun({ text: 'No roadmap phases extracted from the response.', italics: true })],
      }),
    );
  } else {
    for (let i = 0; i < parsed.roadmap.length; i++) {
      const phase = parsed.roadmap[i]!;
      out.push(
        new Paragraph({
          text: `Phase ${i + 1}: ${phase.title}`,
          heading: HeadingLevel.HEADING_2,
        }),
      );
      if (phase.items.length) {
        for (const it of phase.items) {
          out.push(new Paragraph({ children: [new TextRun({ text: `• ${it}` })] }));
        }
      } else {
        out.push(
          new Paragraph({
            children: [new TextRun({ text: 'No details provided.', italics: true })],
          }),
        );
      }
      out.push(new Paragraph({ text: '' }));
    }
  }

  out.push(new Paragraph({ text: 'Risks & mitigations', heading: HeadingLevel.HEADING_1 }));
  if (parsed.risks.length === 0) {
    out.push(
      new Paragraph({
        children: [new TextRun({ text: 'No risks extracted from the response.', italics: true })],
      }),
    );
  } else {
    out.push(
      new Table({
        width: { size: 100, type: WidthType.PERCENTAGE },
        rows: [
          new TableRow({
            children: [
              new TableCell({
                width: { size: 38, type: WidthType.PERCENTAGE },
                children: [new Paragraph({ children: [new TextRun({ text: 'Risk', bold: true })] })],
              }),
              new TableCell({
                width: { size: 62, type: WidthType.PERCENTAGE },
                children: [new Paragraph({ children: [new TextRun({ text: 'Mitigation', bold: true })] })],
              }),
            ],
          }),
          ...parsed.risks.map(
            (r) =>
              new TableRow({
                children: [
                  new TableCell({
                    children: [new Paragraph(r.risk)],
                  }),
                  new TableCell({
                    children: [new Paragraph(r.mitigation)],
                  }),
                ],
              }),
          ),
        ],
      }),
    );
  }

  out.push(new Paragraph({ text: '' }));
  out.push(
    new Paragraph({
      children: [
        new TextRun({
          text: 'Validate assumptions with business and technical owners before commitment.',
          italics: true,
          size: 18,
        }),
      ],
    }),
  );

  return out;
}

export async function exportCompanyAiSolutionsDocx(content: string, baseName?: string): Promise<void> {
  const parsed = await loadParsed(content);
  const name = baseName ?? blueprintBasename();
  const file = new Document({
    sections: [{ children: buildDocxSectionChildren(parsed) }],
  });
  const blob = await Packer.toBlob(file);
  triggerDownload(blob, `${name}.docx`);
}

function renderPdfParsed(
  doc: jsPDF,
  parsed: Awaited<ReturnType<typeof loadParsed>>,
  margin: number,
  pageW: number,
  pageH: number,
): void {
  const maxW = pageW - margin * 2;
  let y = margin;

  const ensureSpace = (neededMm: number) => {
    if (y + neededMm > pageH - margin) {
      doc.addPage();
      y = margin;
    }
  };

  const writeHeading = (text: string, fontSize: number) => {
    doc.setFont('helvetica', 'bold');
    doc.setFontSize(fontSize);
    const lines = doc.splitTextToSize(text, maxW) as string[];
    for (const line of lines) {
      ensureSpace(fontSize * 0.55);
      doc.text(line, margin, y);
      y += fontSize * 0.52;
    }
    y += 3;
  };

  const writeBody = (text: string, fontSize = 10.5) => {
    doc.setFont('helvetica', 'normal');
    doc.setFontSize(fontSize);
    const lines = doc.splitTextToSize(text, maxW) as string[];
    for (const line of lines) {
      ensureSpace(5.5);
      doc.text(line, margin, y);
      y += 5.2;
    }
    y += 1.5;
  };

  writeHeading('Company AI Solutions Blueprint', 16);
  writeBody(
    'Strategic assessment — opportunity areas, solution design, delivery phases, and risk posture. Generated for planning and discussion.',
    9,
  );

  if (parsed.executiveSummary.length) {
    writeHeading('Executive summary', 13);
    parsed.executiveSummary.forEach((item, i) => writeBody(`${i + 1}. ${item}`));
  }

  writeHeading('Context & pressure points', 13);
  writeHeading('Key problems', 11);
  if (parsed.keyProblems.length) {
    parsed.keyProblems.forEach((item) => writeBody(`• ${item}`));
  } else {
    writeBody('No problems extracted from the response.', 9);
  }
  writeHeading('Process improvement areas', 11);
  if (parsed.processAreas.length) {
    parsed.processAreas.forEach((item) => writeBody(`• ${item}`));
  } else {
    writeBody('No process improvements extracted from the response.', 9);
  }

  writeHeading('Recommended solutions', 13);
  if (parsed.solutions.length === 0) {
    writeBody('No structured solution cards found in output.', 9);
  } else {
    parsed.solutions.forEach((s, i) => {
      writeHeading(`${i + 1}. ${s.name}`, 11);
      if (s.type) writeBody(`Type: ${s.type}`);
      if (s.source) writeBody(`Source: ${s.source}`);
      writeBody(`Relevance: ${s.why || 'Not provided'}`);
      writeBody(`Implementation plan: ${s.plan || 'Not provided'}`);
      writeBody(`Dependencies: ${s.dependencies || 'Not provided'}`);
      writeBody(`Expected business impact: ${s.impact || 'Not provided'}`);
      writeBody(`Delivery horizon: ${s.horizon || 'Not provided'}`);
    });
  }

  writeHeading('Implementation roadmap', 13);
  if (parsed.roadmap.length === 0) {
    writeBody('No roadmap phases extracted from the response.', 9);
  } else {
    parsed.roadmap.forEach((phase, i) => {
      writeHeading(`Phase ${i + 1}: ${phase.title}`, 11);
      if (phase.items.length) {
        phase.items.forEach((it) => writeBody(`• ${it}`));
      } else {
        writeBody('No details provided.', 9);
      }
    });
  }

  writeHeading('Risks & mitigations', 13);
  if (parsed.risks.length === 0) {
    writeBody('No risks extracted from the response.', 9);
  } else {
    parsed.risks.forEach((r, i) => {
      writeBody(`Risk ${i + 1}: ${r.risk}`, 10);
      writeBody(`Mitigation: ${r.mitigation}`, 10);
    });
  }

  ensureSpace(8);
  doc.setFont('helvetica', 'italic');
  doc.setFontSize(9);
  doc.setTextColor(90);
  const footerLines = doc.splitTextToSize(
    'Validate assumptions with business and technical owners before commitment.',
    maxW,
  ) as string[];
  for (const line of footerLines) {
    ensureSpace(5);
    doc.text(line, margin, y);
    y += 4.5;
  }
}

export async function exportCompanyAiSolutionsPdf(content: string, baseName?: string): Promise<void> {
  const parsed = await loadParsed(content);
  const name = baseName ?? blueprintBasename();
  const doc = new jsPDF({ unit: 'mm', format: 'a4' });
  const margin = 14;
  const pageW = doc.internal.pageSize.getWidth();
  const pageH = doc.internal.pageSize.getHeight();
  renderPdfParsed(doc, parsed, margin, pageW, pageH);
  doc.save(`${name}.pdf`);
}
