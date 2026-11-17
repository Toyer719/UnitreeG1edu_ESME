"""OSNet x0.25 MSMT17 : caractéristiques corporelles, sans reconnaissance faciale."""
import cv2
import numpy as np
import torch
from .vendor.osnet import osnet_x0_25


class OSNetEncoder:
    def __init__(self, weights, device='cpu'):
        self.device=torch.device(device)
        state=torch.load(weights,map_location='cpu',weights_only=True)
        if 'state_dict' in state:state=state['state_dict']
        state={k.removeprefix('module.'):v for k,v in state.items()}
        self.model=osnet_x0_25(num_classes=state['classifier.weight'].shape[0],pretrained=False)
        self.model.load_state_dict(state,strict=True)
        self.model.eval().to(self.device)
        self.mean=torch.tensor([.485,.456,.406],device=self.device).view(1,3,1,1)
        self.std=torch.tensor([.229,.224,.225],device=self.device).view(1,3,1,1)

    @torch.inference_mode()
    def encoder(self,frame,boxes):
        h,w=frame.shape[:2]
        crops,indices=[],[]
        output=[None]*len(boxes)
        for i,(_,box,conf) in enumerate(boxes):
            x1,y1,x2,y2=box
            if conf<.2 or x2-x1<16 or y2-y1<48:continue
            crop=frame[max(0,y1):min(h,y2),max(0,x1):min(w,x2)]
            if not crop.size:continue
            rgb=cv2.cvtColor(cv2.resize(crop,(128,256)),cv2.COLOR_BGR2RGB)
            crops.append(np.ascontiguousarray(rgb.transpose(2,0,1)))
            indices.append(i)
        if crops:
            batch=torch.from_numpy(np.stack(crops)).to(self.device).float()/255.
            vectors=self.model((batch-self.mean)/self.std)
            vectors=torch.nn.functional.normalize(vectors,dim=1).cpu().numpy()
            for i,v in zip(indices,vectors):output[i]=v
        return output
