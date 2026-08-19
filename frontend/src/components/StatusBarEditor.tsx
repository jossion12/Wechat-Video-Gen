import type { StatusBar } from '../types';
import { DEFAULT_STATUS_BAR } from '../App';

interface StatusBarEditorProps {
  statusBar: StatusBar;
  onChange: (patch: Partial<StatusBar>) => void;
}

/** 判断当前状态栏是否与默认值一致，用于决定"重置默认"按钮是否高亮。 */
function isDefaultStatusBar(sb: StatusBar): boolean {
  return (
    sb.time === DEFAULT_STATUS_BAR.time &&
    sb.battery_level === DEFAULT_STATUS_BAR.battery_level &&
    sb.signal_type === DEFAULT_STATUS_BAR.signal_type &&
    sb.signal_type_secondary === DEFAULT_STATUS_BAR.signal_type_secondary &&
    sb.dual_sim === DEFAULT_STATUS_BAR.dual_sim &&
    sb.show_wifi === DEFAULT_STATUS_BAR.show_wifi &&
    sb.show_signal === DEFAULT_STATUS_BAR.show_signal &&
    sb.show_bluetooth === DEFAULT_STATUS_BAR.show_bluetooth &&
    sb.show_alarm === DEFAULT_STATUS_BAR.show_alarm
  );
}

/** 状态栏设置：时间、电池、信号类型、副卡与应用图标 + 显示开关。 */
export function StatusBarEditor({ statusBar, onChange }: StatusBarEditorProps) {
  const isDefault = isDefaultStatusBar(statusBar);
  return (
    <section className="card">
      <div className="card-header">
        <h2 className="card-title">状态栏</h2>
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          disabled={isDefault}
          onClick={() => onChange({ ...DEFAULT_STATUS_BAR })}
          title={isDefault ? '当前已是默认值' : '还原为默认参考配置'}
        >
          重置默认
        </button>
      </div>
      <div className="form-row">
        <label className="form-label" htmlFor="sb-time">
          时间
        </label>
        <input
          id="sb-time"
          type="text"
          maxLength={8}
          value={statusBar.time}
          placeholder="例如：12:34"
          onChange={(e) => onChange({ time: e.target.value })}
        />
      </div>
      <div className="form-row">
        <label className="form-label" htmlFor="sb-signal">
          信号类型
        </label>
        <select
          id="sb-signal"
          value={statusBar.signal_type ?? ''}
          onChange={(e) =>
            onChange({ signal_type: (e.target.value as '5G' | '4G') || null })
          }
        >
          <option value="">不显示</option>
          <option value="5G">5G</option>
          <option value="4G">4G</option>
        </select>
      </div>
      <div className="form-row">
        <label className="form-label" htmlFor="sb-signal-2">
          副卡信号
        </label>
        <select
          id="sb-signal-2"
          value={statusBar.signal_type_secondary ?? ''}
          onChange={(e) =>
            onChange({ signal_type_secondary: (e.target.value as '5G' | '4G') || null })
          }
        >
          <option value="">不显示</option>
          <option value="5G">5G</option>
          <option value="4G">4G</option>
        </select>
      </div>
      <div className="form-row">
        <span className="form-label">显示选项</span>
        <div className="checkbox-group">
          <label className="checkbox-option">
            <input
              type="checkbox"
              checked={statusBar.show_wifi}
              onChange={(e) => onChange({ show_wifi: e.target.checked })}
            />
            WiFi
          </label>
          <label className="checkbox-option">
            <input
              type="checkbox"
              checked={statusBar.show_signal}
              onChange={(e) => onChange({ show_signal: e.target.checked })}
            />
            信号
          </label>
          <label className="checkbox-option">
            <input
              type="checkbox"
              checked={statusBar.show_bluetooth}
              onChange={(e) => onChange({ show_bluetooth: e.target.checked })}
            />
            蓝牙
          </label>
          <label className="checkbox-option">
            <input
              type="checkbox"
              checked={statusBar.dual_sim}
              onChange={(e) => onChange({ dual_sim: e.target.checked })}
            />
            双卡
          </label>
          <label className="checkbox-option">
            <input
              type="checkbox"
              checked={statusBar.show_alarm}
              onChange={(e) => onChange({ show_alarm: e.target.checked })}
            />
            闹钟
          </label>
        </div>
      </div>
    </section>
  );
}
