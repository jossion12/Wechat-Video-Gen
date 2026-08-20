export interface WizardStep {
  id: number;
  title: string;
}

interface StepperProps {
  steps: WizardStep[];
  currentStep: number;
  onStepClick: (stepId: number) => void;
}

/**
 * 顶部步骤指示器：数字圆形 + 标题 + 连接线。
 * 当前步骤高亮为霓虹蓝，已完成步骤显示对勾且可点击回退，
 * 未到达步骤禁用。
 */
export function Stepper({ steps, currentStep, onStepClick }: StepperProps) {
  return (
    <nav className="stepper" aria-label="步骤">
      {steps.map((step, index) => {
        const isActive = step.id === currentStep;
        const isCompleted = step.id < currentStep;
        const isClickable = isCompleted;
        return (
          <div key={step.id} className="stepper-step-wrapper">
            <button
              type="button"
              className={`stepper-step${isActive ? ' stepper-step--active' : ''}${
                isCompleted ? ' stepper-step--completed' : ''
              }`}
              disabled={!isClickable && !isActive}
              onClick={() => isClickable && onStepClick(step.id)}
              aria-current={isActive ? 'step' : undefined}
            >
              <span className="stepper-circle">{isCompleted ? '✓' : step.id}</span>
              <span className="stepper-title">{step.title}</span>
            </button>
            {index < steps.length - 1 && (
              <div
                className={`stepper-line${
                  isCompleted ? ' stepper-line--completed' : ''
                }`}
              />
            )}
          </div>
        );
      })}
    </nav>
  );
}
