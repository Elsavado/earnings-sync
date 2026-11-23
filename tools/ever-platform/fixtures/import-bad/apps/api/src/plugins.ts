// Allowed: the API's plugin list imports the modules through their entry points.
import { EverConnectPlugin } from '@irtranscripts/plugin-ever-connect';
import { EverStatsPlugin } from '@irtranscripts/plugin-ever-stats';
export const plugins = [EverConnectPlugin, EverStatsPlugin];
