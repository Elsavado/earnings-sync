import { type CSSProperties, type ReactNode } from 'react';
import { type NbStatus } from '../themeTokens';

export interface BadgeProps {
	/** Badge text (Nebular `[text]`). */
	text?: ReactNode;
	/** Nebular status; drives `--badge-<status>-*` colours. */
	status?: NbStatus;
	className?: string;
	style?: CSSProperties;
}

/**
 * Badge — theme-adaptive port of `<nb-badge>` in its "unpositioned" dashboard form: the compact
 * table chip of the Time Tracking SCSS (`position: unset; display: inline-flex; margin: 0`, sized
 * from the `irtranscripts-table-badge-*` / `irtranscripts-table-chip-*` tokens).
 */
export function Badge({ text, status = 'basic', className, style }: BadgeProps) {
	return (
		<span
			className={className}
			style={{
				display: 'inline-flex',
				alignItems: 'center',
				justifyContent: 'center',
				margin: 0,
				height: 'var(--irtranscripts-table-badge-height, 1.25rem)',
				padding: 'var(--irtranscripts-table-chip-padding-y, 0.0625rem) var(--irtranscripts-table-chip-padding-x, 0.375rem)',
				borderRadius: 'var(--irtranscripts-radius-sm, 0.375rem)',
				background: `var(--badge-${status}-background-color)`,
				color: `var(--badge-${status}-text-color)`,
				fontFamily: 'var(--badge-text-font-family)',
				fontSize: 'var(--irtranscripts-table-chip-font-size, 0.6875rem)',
				fontWeight: 600,
				lineHeight: 'var(--irtranscripts-table-chip-line-height, 0.875rem)',
				fontVariantNumeric: 'tabular-nums',
				textAlign: 'center',
				whiteSpace: 'nowrap',
				...style
			}}
		>
			{text}
		</span>
	);
}
