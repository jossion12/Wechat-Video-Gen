import { useRef, useState } from 'react';
import { uploadFile } from '../../api';

interface AvatarPickerProps {
  value: string | null;
  onChange: (url: string | null) => void;
  kind?: 'avatar' | 'image';
  alt?: string;
}

/** 图片选择器：上传 → 缩略图预览 → 可移除。头像与消息图片共用。 */
export function AvatarPicker({
  value,
  onChange,
  kind = 'avatar',
  alt = '图片',
}: AvatarPickerProps) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const pickFile = async (file: File | undefined) => {
    if (!file) return;
    setUploading(true);
    setError(null);
    try {
      const { url } = await uploadFile(file, kind);
      onChange(url);
    } catch (err) {
      setError(err instanceof Error ? err.message : '上传失败');
    } finally {
      setUploading(false);
      if (inputRef.current) {
        inputRef.current.value = '';
      }
    }
  };

  return (
    <div className={`avatar-picker avatar-picker--${kind}`}>
      {value ? (
        <div className="avatar-thumb">
          <img src={value} alt={alt} />
          <button
            type="button"
            className="avatar-remove"
            title="移除图片"
            onClick={() => onChange(null)}
          >
            ×
          </button>
        </div>
      ) : (
        <button
          type="button"
          className={`avatar-placeholder${uploading ? ' avatar-placeholder--busy' : ''}`}
          disabled={uploading}
          onClick={() => inputRef.current?.click()}
        >
          {uploading ? '上传中…' : kind === 'avatar' ? '上传头像' : '上传图片'}
        </button>
      )}
      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        hidden
        onChange={(e) => {
          void pickFile(e.target.files?.[0]);
        }}
      />
      {error && <div className="field-error">{error}</div>}
    </div>
  );
}
