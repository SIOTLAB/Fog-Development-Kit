# Credit to Moses Olafenwa for the sample program, dataset, trained models, and
# the imageai library
# https://towardsdatascience.com/object-detection-with-10-lines-of-code-d6cb4d86f606

# Datasets:
# https://github.com/OlafenwaMoses/ImageAI/releases/download/1.0/resnet50_coco_best_v2.0.1.h5
# wget https://github.com/fchollet/deep-learning-models/releases/download/v0.2/resnet50_weights_tf_dim_ordering_tf_kernels.h5

# We integrate this application into the FDK as an example of how an important,
# real-world application can run on top of the platform, such as an object
# detection system.

from imageai.Detection import ObjectDetection
import os
import sys
import time

def main():
    # Get filename to write to
    try:
        fn = sys.argv[1]
    except IndexError:
        print("Error: No filename given.", file=sys.stderr)
        sys.exit(1)

    start_time = time.time()
    # Setup obj detection
    execution_path = os.getcwd()
    detector = ObjectDetection()
    detector.setModelTypeAsRetinaNet()
    detector.setModelPath(execution_path + "/resnet50_coco_best_v2.0.1.h5")
    # detector.setModelTypeAsTinyYOLOv3()
    # detector.setModelPath(execution_path + "/yolo-tiny.h5")
    detector.loadModel()
    detections = detector.detectObjectsFromImage(input_image=os.path.join(execution_path , fn), output_image_path=os.path.join(execution_path , "new-"+fn))

    for eachObject in detections:
        print(eachObject["name"] , " : " , eachObject["percentage_probability"])

    duration = time.time() - start_time
    print("Time taken: " + str(duration))
    sys.exit(0)
    
if __name__ == "__main__":
    main()
