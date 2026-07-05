export default function Modal({ open, title, onClose, children }) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60" onClick={onClose}>
      <div
        className="bg-surface border border-border rounded-xl w-full max-w-lg max-h-[85vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-5 py-4 border-b border-border">
          <h2 className="text-gray-100 font-medium">{title}</h2>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-200">✕</button>
        </div>
        <div className="p-5">{children}</div>
      </div>
    </div>
  );
}
