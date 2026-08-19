import type { ReactNode } from 'react';
import { Stepper, type WizardStep } from './Stepper';

export type { WizardStep };

interface StepHint {
  ok: boolean;
  text: string;
}

interface WizardLayoutProps {
  steps: WizardStep[];
  currentStep: number;
  onStepClick: (stepId: number) => void;
  form: ReactNode;
  preview: ReactNode;
  extraPreview?: ReactNode;
  footerLeft: ReactNode;
  footerRight: ReactNode;
  hint: StepHint | null;
}

/**
 * 向导整体布局：顶部步骤条、中部滚动双栏（左侧表单 + 右侧预览）、
 * 底部固定按钮栏。切换步骤时左侧表单有淡入动画。
 */
export function WizardLayout({
  steps,
  currentStep,
  onStepClick,
  form,
  preview,
  extraPreview,
  footerLeft,
  footerRight,
  hint,
}: WizardLayoutProps) {
  return (
    <div className="wizard-layout">
      <Stepper steps={steps} currentStep={currentStep} onStepClick={onStepClick} />
      <div className="wizard-scroll">
        <main className="wizard-main">
          <div className="wizard-form">
            <div key={currentStep} className="wizard-step">
              {form}
            </div>
            {hint && (
              <div className={`step-hint${hint.ok ? '' : ' step-hint--error'}`}>
                {hint.ok ? '✓ ' : '✗ '}
                {hint.text}
              </div>
            )}
          </div>
          <div className="wizard-preview">
            {preview}
            {extraPreview}
          </div>
        </main>
      </div>
      <footer className="wizard-footer">
        <div className="wizard-footer-left">{footerLeft}</div>
        <div className="wizard-footer-right">{footerRight}</div>
      </footer>
    </div>
  );
}
