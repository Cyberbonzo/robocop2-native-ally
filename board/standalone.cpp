// The native title has its own frontend, ROM identity and fixed video layout.
// FBNeo's optional patch, cheat and bezel services are not part of this board.
#include "burnint.h"
RomDataInfo *pRDI = nullptr;
BurnRomInfo *pDataRomDesc = nullptr;
bool bDoIpsPatch = false;
UINT32 nIpsMemExpLen[SND2_ROM+1] = {};
void IpsApplyPatches(UINT8 *, char *, UINT32, bool) {}
void CpuCheatRegister(INT32, cpu_core_config *) {}
void HiscoreReset(INT32) {}
INT32 BurnArtworkGetDisplaySize(INT32 *, INT32 *) { return 0; }
INT32 BurnArtworkGetAspect(INT32 *, INT32 *) { return 0; }

// EEPROM (settings, high scores) is persisted only when the frontend names a
// save folder; the default path cannot be opened, so tests never write files.
TCHAR szAppEEPROMPath[MAX_PATH] = "/dev/null/";
// No artwork overlays: BurnDrvRedraw brackets each frame with these.
void BurnArtworkFrameBegin() {}
void BurnArtworkFrameEnd() {}
