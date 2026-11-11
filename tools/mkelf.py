import sys,struct
src,dst,base,entry=sys.argv[1],sys.argv[2],int(sys.argv[3],16),int(sys.argv[4],16)
d=open(src,'rb').read()
ehdr_sz,ph_sz=52,32
off=0x1000
# ELF32 LE ARM, EF_ARM_EABI_VER5
eh=b'\x7fELF'+bytes([1,1,1,0])+b'\0'*8
eh+=struct.pack('<HHIIIIIHHHHHH',2,40,1,entry,ehdr_sz,0,0x05000200,ehdr_sz,ph_sz,1,0,0,0)
ph=struct.pack('<IIIIIIII',1,off,base,base,len(d),len(d),5,0x1000)
out=eh+ph; out+=b'\0'*(off-len(out))+d
open(dst,'wb').write(out)
