// Known-bad: a module's file instead of its entry point, and a lazy import of a module.
import { readEverConnectConfig } from '@irtranscripts/plugin-ever-connect/src/lib/ever-connect-config';
export const lazy = () => import('@irtranscripts/plugin-ever-stats-ui');
export { readEverConnectConfig };
// A specifier inside a string is not an import: "import x from '@irtranscripts/plugin-ever-connect'"
