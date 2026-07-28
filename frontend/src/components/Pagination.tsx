import { Pagination as BsPagination } from "react-bootstrap";

export interface PaginationProps {
  page: number;
  pageSize: number;
  total: number;
  pages: number;
  onPageChange: (page: number) => void;
}

export function Pagination(props: PaginationProps) {
  const { page, pages, onPageChange } = props;

  if (pages <= 1) {
    return null;
  }

  const items: Array<number | "ellipsis"> = [];
  const push = (value: number | "ellipsis") => items.push(value);

  const rangeStart = Math.max(1, page - 2);
  const rangeEnd = Math.min(pages, page + 2);

  if (rangeStart > 1) {
    push(1);
    if (rangeStart > 2) {
      push("ellipsis");
    }
  }
  for (let i = rangeStart; i <= rangeEnd; i += 1) {
    push(i);
  }
  if (rangeEnd < pages) {
    if (rangeEnd < pages - 1) {
      push("ellipsis");
    }
    push(pages);
  }

  return (
    <BsPagination className="mb-0">
      <BsPagination.Prev disabled={page <= 1} onClick={() => onPageChange(Math.max(1, page - 1))} />
      {items.map((item, index) =>
        item === "ellipsis" ? (
          <BsPagination.Ellipsis key={`ellipsis-${index}`} disabled />
        ) : (
          <BsPagination.Item
            key={item}
            active={item === page}
            onClick={() => onPageChange(item)}
          >
            {item}
          </BsPagination.Item>
        ),
      )}
      <BsPagination.Next disabled={page >= pages} onClick={() => onPageChange(Math.min(pages, page + 1))} />
    </BsPagination>
  );
}
