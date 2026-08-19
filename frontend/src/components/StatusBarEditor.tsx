import type { StatusBar } from '../types';

interface StatusBarEditorProps {
  statusBar: StatusBar;
  onChange: (patch: Partial<StatusBar>) => void;
}

/** 状态栏设置：时间、电池、网速、信号与图标开关。 */
export function StatusBarEditor({ statusBar, onChange }: StatusBarEditorProps) {
  return (
    <section className="card">
      <h2 className="card-title">状态栏</h2>
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
        <label className="form-label" htmlFor="sb-battery">
          电池电量
        </label>
        <input
          id="sb-battery"
          type="number"
          min={0}
          max={100}
          value={statusBar.battery_level}
          onChange={(e) => onChange({ battery_level: Number(e.target.value) })}
        />
      </div>
      <div className="form-row">
        <label className="form-label" htmlFor="sb-speed">
          网速
        </label>
        <input
          id="sb-speed"
          type="text"
          value={statusBar.network_speed ?? ''}
          placeholder="例如：3.5 K/s，留空则不显示"
          onChange={(e) =>
            onChange({ network_speed: e.target.value.trim() || null })
          }
        />
      </div>
      <div className="form-row">
        <label className="form-label" htmlFor="sb-signal">
          信号类型
        </label>
        <input
          id="sb-signal"
          type="text"
          value={statusBar.signal_type ?? ''}
          placeholder="例如：5G、4G，留空则不显示"
          onChange={(e) =>
            onChange({ signal_type: e.target.value.trim() || null })
          }
        />
      </div>
      <div className="form-row">
        <label className="form-label" htmlFor="sb-signal-2">
          副卡信号
        </label>
        <input
          id="sb-signal-2"
          type="text"
          value={statusBar.signal_type_secondary ?? ''}
          placeholder="双卡时显示，例如：5G"
          onChange={(e) =>
            onChange({ signal_type_secondary: e.target.value.trim() || null })
          }
        />
      </div>
      <div className="form-row">
        <label className="form-label" htmlFor="sb-app-icons">
          应用图标
        </label>
        <input
          id="sb-app-icons"
          type="text"
          value={statusBar.app_icons.join(',')}
          placeholder="例如：bilibili,微信（或用图片 URL）"
          onChange={(e) =>
            onChange({
              app_icons: e.target.value
                .split(',')
                .map((s) => s.trim())
                .filter(Boolean),
            })
          }
        />
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
          <label className="checkbox-option">
            <input
              type="checkbox"
              checked={statusBar.show_nfc}
              onChange={(e) => onChange({ show_nfc: e.target.checked })}
            />
            NFC
          </label>
        </div>
      </div>
    </section>
  );
}
