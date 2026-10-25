from fastapi import APIRouter, Depends, HTTPException, status

from schemas.dataset import (
    DatasetBuildRequest,
    DatasetBuildResponse,
)
from services.dataset_service import (
    build_gpt_sovits_dataset,
)
from services.segmented_dataset_service import SegmentedDatasets, DatasetError
from services.transcript_review_service import TranscriptReviews
from schemas.segmented_dataset import SegmentDatasetRequest, SegmentDatasetManifest, DatasetList
from config import DATASETS_DIR, UPLOAD_DIR, TRANSCRIPTS_DIR, CHARACTERS_DIR

def get_segmented():
    return SegmentedDatasets(DATASETS_DIR,UPLOAD_DIR,TranscriptReviews(TRANSCRIPTS_DIR,UPLOAD_DIR),CHARACTERS_DIR)

def dataset_call(method,*args):
    try:return method(*args)
    except DatasetError as error:raise HTTPException(error.status_code,str(error)) from error


router = APIRouter(
    prefix="/api/datasets",
    tags=["Datasets"],
)

@router.post('/segments',status_code=201,response_model=SegmentDatasetManifest)
def build_segments(request:SegmentDatasetRequest,datasets=Depends(get_segmented)):
    return dataset_call(datasets.build,request)

@router.get('',response_model=DatasetList)
def list_datasets(datasets=Depends(get_segmented)):
    return dataset_call(datasets.list)

@router.get('/{name}',response_model=dict)
def get_dataset(name:str,datasets=Depends(get_segmented)):
    return dataset_call(datasets.get,name)


@router.post(
    "/build",
    response_model=DatasetBuildResponse,
    status_code=status.HTTP_201_CREATED,
)
def build_dataset(request: DatasetBuildRequest):
    return build_gpt_sovits_dataset(request)
